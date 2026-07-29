"""aoto: catalog loading, HTTP aggregation, and the group/command menu tree.

Real HTTP is faked by monkeypatching aoto._request; disk is used only for the
catalog-loading tests via tmp files.
"""
import json

import pytest

from core import aoto
from core.constants import After, Kind
from core.model import ActionNode, MenuNode


@pytest.fixture
def catalog(monkeypatch):
    """In-memory groups/commands/status caches, no disk or network."""
    groups = {"Зал1": ["10.0.0.1:8080", "10.0.0.2:8080"], "Зал2": ["10.0.0.3:8080"]}
    commands = [
        {"label": "Блэкаут", "method": "POST", "path": "/set", "body": {"type": 1}},
        {"label": "Статус", "method": "POST", "path": "/get", "body": {}, "response_field": "data.type"},
    ]
    monkeypatch.setattr(aoto, "_groups", dict(groups))
    monkeypatch.setattr(aoto, "_commands", list(commands))
    monkeypatch.setattr(aoto, "_status", {})
    return {"groups": groups, "commands": commands}


# --- catalog loading (disk) -----------------------------------------------
def test_load_groups_parses_addresses_comments_and_prefix(tmp_path, monkeypatch):
    d = tmp_path / "groups"
    d.mkdir()
    (d / "01_Зал.txt").write_text(
        "# a comment\n10.0.0.1:8080\n\n10.0.0.2:8080  # inline\n", encoding="utf-8")
    monkeypatch.setattr(aoto, "AOTO_GROUPS_DIR", d)
    out = aoto._load_groups()
    assert out == {"Зал": ["10.0.0.1:8080", "10.0.0.2:8080"]}  # NN_ prefix stripped


def test_load_commands_ignores_labelless_note_objects(tmp_path, monkeypatch):
    f = tmp_path / "commands.json"
    f.write_text(json.dumps([
        {"note": "just a comment"},
        {"label": "Вход", "path": "/set", "body": {"type": 0}},
    ]), encoding="utf-8")
    monkeypatch.setattr(aoto, "AOTO_COMMANDS_FILE", f)
    cmds = aoto._load_commands()
    assert [c["label"] for c in cmds] == ["Вход"]


def test_load_commands_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(aoto, "AOTO_COMMANDS_FILE", tmp_path / "nope.json")
    assert aoto._load_commands() == []


# --- response extraction --------------------------------------------------
def test_extract_dotted_path():
    assert aoto._extract('{"data": {"type": 2}}', "data.type") == 2
    assert aoto._extract('{"data": {}}', "data.type") is None
    assert aoto._extract("not json", "data.type") == "not json"


# --- aggregation ----------------------------------------------------------
def test_action_text_ok_and_partial():
    assert aoto._action_text([("a", True, None), ("b", True, None)]) == "OK 2/2"
    assert aoto._action_text([("a", True, None), ("b", False, None)]) == "ERR 1/2"


def test_status_text_agrees_differs_partial_errors():
    st = {"label": "S", "response_field": "obj.brightness"}
    assert aoto._status_text(st, [("a", True, 225), ("b", True, 225)]) == "225"      # equal
    assert aoto._status_text(st, [("a", True, 200), ("b", True, 225)]) == "200-225"  # range
    assert aoto._status_text(st, [("a", True, 200), ("b", False, None)]) == "200 (1/2)"  # partial
    assert aoto._status_text(st, [("a", False, None)]) == "ERR"                      # all failed


def test_map_applies_labels():
    hdr = {"labels": {"0": "from input", "2": "HLG"}}
    assert aoto._map(hdr, 2) == "HLG"
    assert aoto._map(hdr, 9) == 9            # unmapped -> raw value
    assert aoto._map({}, 2) == 2             # no labels


def test_status_text_uses_labels_and_lists_when_differ():
    hdr = {"response_field": "obj.hdrSetting", "labels": {"1": "SDR", "3": "PQ"}}
    assert aoto._status_text(hdr, [("a", True, 1), ("b", True, 1)]) == "SDR"
    assert aoto._status_text(hdr, [("a", True, 1), ("b", True, 3)]) == "SDR/PQ"


def test_values_differ():
    hdr = {"labels": {"1": "SDR", "3": "PQ"}}
    assert aoto._values_differ(hdr, [("a", True, 1), ("b", True, 1)]) is False
    assert aoto._values_differ(hdr, [("a", True, 1), ("b", True, 3)]) is True
    assert aoto._values_differ(hdr, [("a", True, 1), ("b", False, None)]) is False


def test_format_values_range_and_categorical():
    assert aoto._format_values([100, 225, 200]) == "100-225"   # numeric spread
    assert aoto._format_values([2.0, 2.0]) == "2"              # float int shown clean
    assert aoto._format_values(["a", "b", "a"]) == "a/b"       # categorical distinct list


def test_run_group_hits_every_address(catalog, monkeypatch):
    seen = []

    def fake_request(addr, cmd):
        seen.append(addr)
        return (True, None)

    monkeypatch.setattr(aoto, "_request", fake_request)
    msg = aoto.run_group("Зал1", catalog["commands"][0])
    assert sorted(seen) == ["10.0.0.1:8080", "10.0.0.2:8080"]
    assert msg == "OK 2/2"


def test_run_group_no_addresses(monkeypatch):
    monkeypatch.setattr(aoto, "_groups", {})
    assert aoto.run_group("Ghost", {"label": "X"}) == "нет адресов"


# --- menu tree ------------------------------------------------------------
def test_attach_inserts_after_pc_and_pdq():
    root = MenuNode("", None, "", children=[
        MenuNode("__pc__", None, "ПК"), MenuNode("__pdq__", None, "PDQ"),
        MenuNode("other", None, "Other")])
    aoto.attach(root)
    assert [c.name for c in root.children] == ["__pc__", "__pdq__", "__aoto__", "other"]


def test_attach_at_top_when_no_pc_pdq():
    root = MenuNode("", None, "", children=[MenuNode("other", None, "Other")])
    aoto.attach(root)
    assert root.children[0].name == "__aoto__"


def test_aoto_children_lists_groups(catalog):
    kids = aoto._aoto_children(None)
    assert [k.name for k in kids] == ["Зал1", "Зал2"]
    assert all(isinstance(k, MenuNode) for k in kids)
    assert kids[0].context == {"group": "Зал1"}


def test_group_commands_builds_action_and_status_buttons(catalog):
    node = MenuNode("Зал1", None, "Зал1", context={"group": "Зал1"})
    action, status = aoto._group_commands(node)
    assert isinstance(action, ActionNode) and action.after == After.TEXT and action.label == "Блэкаут"
    # empty cache -> not differing -> a plain re-poll ActionNode
    assert isinstance(status, ActionNode) and status.after == After.RERENDER and status.label == "Статус"


def test_status_button_shows_cached_value_and_press_refreshes(catalog, monkeypatch):
    monkeypatch.setattr(aoto, "_request", lambda addr, cmd: (True, 2))

    node = MenuNode("Зал2", None, "Зал2", context={"group": "Зал2"})
    status = aoto._group_commands(node)[1]
    status.on_press()                       # polls, writes cache
    results = aoto._cached_results("Зал2", "Статус")
    assert aoto._status_text(catalog["commands"][1], results) == "2"
    refreshed = aoto._group_commands(node)[1]
    assert refreshed.label == "Статус\n2"   # label now reflects the cache


def test_status_differ_becomes_drilldown_with_per_ip_breakdown(catalog, monkeypatch):
    hdr = {"label": "HDR", "method": "POST", "path": "/get", "body": {},
           "response_field": "obj.hdrSetting", "labels": {"1": "SDR", "3": "PQ"}}
    monkeypatch.setattr(aoto, "_commands", [hdr])
    # Зал1 = 10.0.0.1 + 10.0.0.2 -> make them disagree
    monkeypatch.setattr(aoto, "_request",
                        lambda addr, cmd: (True, 1 if addr.endswith(".1:8080") else 3))
    aoto._poll_statuses()

    node = MenuNode("Зал1", None, "Зал1", context={"group": "Зал1"})
    hdr_btn = aoto._group_commands(node)[0]
    assert isinstance(hdr_btn, MenuNode)              # disagreement -> drill-in menu
    assert hdr_btn.label == "HDR\nSDR/PQ"

    detail = aoto._status_detail(hdr_btn)
    assert sorted(b.label for b in detail) == [".1\nSDR", ".2\nPQ"]  # last octet -> value


def test_action_button_press_sends_and_summarizes(catalog, monkeypatch):
    monkeypatch.setattr(aoto, "_request", lambda addr, cmd: (True, None))
    node = MenuNode("Зал1", None, "Зал1", context={"group": "Зал1"})
    action = aoto._group_commands(node)[0]
    assert action.on_press() == "OK 2/2"


def test_poll_statuses_fills_cache_for_status_commands_only(catalog, monkeypatch):
    monkeypatch.setattr(aoto, "_request", lambda addr, cmd: (True, 1))
    aoto._poll_statuses()
    st_cmd = catalog["commands"][1]
    # status command cached for both groups; the action command is not polled
    assert aoto._status_text(st_cmd, aoto._cached_results("Зал1", "Статус")) == "1"
    assert aoto._status_text(st_cmd, aoto._cached_results("Зал2", "Статус")) == "1"
    assert aoto._cached_results("Зал1", "Блэкаут") == []
