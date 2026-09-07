"""aotopresets: preset store (disk tree), parsing, apply/capture, and the browser menu.

Disk is a tmp tree under aotopresets.AOTO_PRESETS_DIR; HTTP is faked by
monkeypatching aotopresets.aoto.probe, so no live controllers are touched.
"""
import json

import pytest

from core import aotopresets, aoto
from core.constants import After, Kind
from core.model import ActionNode, MenuNode


def _write(root, rel, data):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        p.write_text(data, encoding="utf-8")
    else:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A tmp preset root wired into the module; catalog + one nested preset."""
    root = tmp_path / "presets"
    root.mkdir()
    monkeypatch.setattr(aotopresets, "AOTO_PRESETS_DIR", root)
    _write(root, "01_Заставка/01_вечер.json", [
        {"name": "Вход", "set": {"path": "/s", "key": "type", "value": 2},
         "get": {"path": "/g", "field": "obj.type"}},
    ])
    _write(root, "02_Зал.json", [
        {"name": "Вход", "set": {"path": "/s", "key": "type", "value": 0},
         "get": {"path": "/g", "field": "obj.type"}},
    ])
    _write(root, "parameters.json", {"parameters": [
        {"name": "Вход", "set": {"path": "/s", "key": "type"},
         "get": {"path": "/g", "field": "obj.type"}},
        {"name": "HDR", "map": {"1": 2, "2": 3, "3": 4},
         "set": {"path": "/h", "key": "hdrSetting", "extra": {"maximumBrightness": 10000}},
         "get": {"path": "/gh", "field": "obj.hdrSetting"}},
    ]})
    aotopresets.refresh()
    return root


@pytest.fixture(autouse=True)
def _clean():
    """Start each test from a pristine module state (no leftover from other tests)."""
    aotopresets._tree = {}
    aotopresets._parameters = []
    aotopresets._available = False
    aotopresets._msgs = {}
    yield


# --- naming / filters -------------------------------------------------------
def test_label_strips_prefix():
    assert aotopresets._label("01_Заставка") == "Заставка"
    assert aotopresets._label("02_Зал.json".replace(".json", "")) == "Зал"
    assert aotopresets._preset_label("01_вечер.json") == "вечер"


def test_is_preset_file_excludes_hidden_and_parameters():
    from pathlib import Path
    assert aotopresets._is_preset_file(Path("02_Зал.json"))
    assert not aotopresets._is_preset_file(Path("parameters.json"))
    assert not aotopresets._is_preset_file(Path("parameters.example.json"))
    assert not aotopresets._is_preset_file(Path(".hidden.json"))
    assert not aotopresets._is_preset_file(Path("_meta.json"))


# --- parsing ----------------------------------------------------------------
def test_parse_preset_list_and_params_wrapper():
    body = [{"set": {"path": "/s", "key": "type", "value": 0}}]
    assert aotopresets.parse_preset(body, "x") == body
    assert aotopresets.parse_preset({"params": body}, "x") == body


def test_parse_preset_drops_unapplyable_rows(caplog):
    data = [
        {"set": {"path": "/s", "key": "type", "value": 0}},
        {"set": {"path": "/s", "key": "type"}},           # no value
        {"set": {"path": "/s"}},                          # no key
        "junk",
    ]
    out = aotopresets.parse_preset(data, "x")
    assert len(out) == 1
    assert "dropped" in caplog.text


def test_parse_preset_rejects_non_array():
    assert aotopresets.parse_preset({"a": 1}, "x") == []


def test_parse_catalog_needs_set_and_get():
    data = [
        {"set": {"path": "/s", "key": "t"}, "get": {"path": "/g", "field": "o.t"}},
        {"set": {"path": "/s", "key": "t"}},               # no get
        "junk",
    ]
    assert len(aotopresets.parse_catalog(data, "x")) == 1


def test_read_command_carries_optional_get_body():
    cmd = aotopresets._read_command(
        {"get": {"path": "/i", "field": "obj.testPicEn", "body": {"id": 1}}})
    assert cmd["body"] == {"id": 1}
    assert cmd["response_field"] == "obj.testPicEn"
    # no body in the spec -> empty object (as the API expects POST {} reads)
    cmd2 = aotopresets._read_command({"get": {"path": "/g", "field": "obj.b"}})
    assert cmd2["body"] == {}


# --- disk tree --------------------------------------------------------------
def test_refresh_scans_folders_presets_and_catalog(store):
    assert aotopresets.available()
    assert len(aotopresets.parameters()) == 2
    root = sorted(aotopresets.list_dir(""), key=lambda e: e["name"])
    assert [(e["type"], e["label"]) for e in root] == [
        ("folder", "Заставка"), ("preset", "Зал")]
    inner = aotopresets.list_dir("01_Заставка")
    assert inner[0]["type"] == "preset" and inner[0]["label"] == "вечер"
    assert inner[0]["params"][0]["set"]["value"] == 2


def test_invalid_preset_json_is_skipped(store, caplog):
    _write(store, "bad.json", "[1]")
    aotopresets.refresh()
    names = [e["name"] for e in aotopresets.list_dir("")]
    assert "bad.json" not in names


def test_empty_or_example_only_store_availability(tmp_path, monkeypatch):
    monkeypatch.setattr(aotopresets, "AOTO_PRESETS_DIR", tmp_path)
    aotopresets.refresh()
    assert not aotopresets.available()          # empty dir -> no preset browser
    _write(tmp_path, "parameters.example.json", {"parameters": []})
    aotopresets.refresh()
    assert aotopresets.available()              # template present -> can start


# --- apply ------------------------------------------------------------------
def test_apply_preset_aggregates_over_params_and_controllers(store, monkeypatch):
    seen = {}

    def fake_probe(group, cmd):
        seen.setdefault(group, []).append(cmd)
        return [("a", True, None), ("b", True, None)]

    monkeypatch.setattr(aotopresets.aoto, "probe", fake_probe)
    params = aotopresets.list_dir("")[1]["params"]           # 02_Зал.json (1 param)
    assert aotopresets.apply_preset("Зал", params) == "OK 2/2"
    assert seen["Зал"] == [{"method": "POST", "path": "/s",
                            "body": {"type": 0}}]


def test_apply_preset_failure_count_and_extra_body(store, monkeypatch):
    calls = []

    def fake_probe(group, cmd):
        calls.append(cmd)
        return [("a", True, None), ("b", False, None)]

    monkeypatch.setattr(aotopresets.aoto, "probe", fake_probe)
    hdr_param = {"set": {"path": "/h", "key": "hdrSetting", "value": 3,
                         "extra": {"coefficient": 1}}}
    assert aotopresets.apply_preset("Зал", [hdr_param, hdr_param]) == "ERR 2/4"
    assert calls[0]["body"] == {"hdrSetting": 3, "coefficient": 1}


def test_apply_preset_no_addresses(store, monkeypatch):
    monkeypatch.setattr(aotopresets.aoto, "probe", lambda *a, **k: [])
    assert aotopresets.apply_preset("Зал", [{"set": {"path": "/s", "key": "t", "value": 1}}]) == "нет адресов"


# --- capture ----------------------------------------------------------------
def _agreeing_probe(values_by_field):
    def fake(group, cmd):
        val = values_by_field[cmd["response_field"]]
        return [("a", True, val), ("b", True, val)]
    return fake


def test_capture_writes_preset_from_agreed_values(store, monkeypatch):
    monkeypatch.setattr(aotopresets.aoto, "probe",
                        _agreeing_probe({"obj.type": 0, "obj.hdrSetting": 1}))
    assert aotopresets.capture_preset("Зал", "") == ""
    entries = [e for e in aotopresets.list_dir("") if e["type"] == "preset"]
    names = [e["label"] for e in entries]
    assert "Новый пресет 3" in names          # auto-named after the max NN prefix (02 -> 03)
    new = next(e for e in entries if e["label"] == "Новый пресет 3")
    data = json.loads((store / new["name"]).read_text(encoding="utf-8"))
    by_name = {p["name"]: p for p in data}
    assert by_name["Вход"]["set"] == {"path": "/s", "key": "type", "value": 0}
    assert by_name["Вход"]["get"] == {"path": "/g", "field": "obj.type"}
    # HDR read value 1 is mapped to the write value 2 and stored for apply
    assert by_name["HDR"]["set"] == {"path": "/h", "key": "hdrSetting", "value": 2,
                                     "extra": {"maximumBrightness": 10000}}
    assert "OK 2" in aotopresets._last_msg("Зал", "")


def test_capture_skips_disagreeing_and_failing_params(store, monkeypatch):
    def fake(group, cmd):
        if cmd["response_field"] == "obj.type":
            return [("a", True, 0), ("b", True, 1)]        # disagree -> skip
        if cmd["response_field"] == "obj.hdrSetting":
            return [("a", False, None), ("b", False, None)]  # read error -> skip
        return []

    monkeypatch.setattr(aotopresets.aoto, "probe", fake)
    aotopresets.capture_preset("Зал", "")
    assert "нет общих значений" in aotopresets._last_msg("Зал", "")
    assert not [e for e in aotopresets.list_dir("") if e["type"] == "preset"
                and e["label"].startswith("Новый")]


def test_capture_without_catalog_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(aotopresets, "AOTO_PRESETS_DIR", tmp_path)
    aotopresets.refresh()
    aotopresets.capture_preset("Зал", "")
    assert "нет параметров" in aotopresets._last_msg("Зал", "")


def test_capture_numbers_increment(store, monkeypatch):
    monkeypatch.setattr(aotopresets.aoto, "probe",
                        _agreeing_probe({"obj.type": 1, "obj.hdrSetting": 3}))
    aotopresets.capture_preset("Зал", "")
    aotopresets.capture_preset("Зал", "")
    labels = [e["label"] for e in aotopresets.list_dir("") if e["type"] == "preset"]
    assert "Новый пресет 3" in labels and "Новый пресет 4" in labels  # 02_Зал -> 03, 04


def test_make_folder_creates_and_refreshes(store):
    assert aotopresets.make_folder("") == ""
    labels = [e["label"] for e in aotopresets.list_dir("") if e["type"] == "folder"]
    assert "Новая папка 3" in labels               # after NN prefixes 01/02
    assert (store / "03_Новая папка 3").is_dir()


# --- menu tree --------------------------------------------------------------
def test_group_presets_node_gated_on_availability():
    aotopresets._available = False
    assert aotopresets.group_presets_node("Зал") is None


def test_folder_children_layout_and_actions(store, monkeypatch):
    seen = []
    monkeypatch.setattr(aotopresets.aoto, "probe",
                        lambda g, c: seen.append(c) or [("a", True, None)])
    node = aotopresets.group_presets_node("Зал")
    assert node is not None and node.label == "Пресеты" and node.context == {"group": "Зал", "rel": ""}
    kids = aotopresets._folder_children(node)
    by_name = {k.name: k for k in kids}
    assert by_name["__capture__"].label == "Записать пресет"
    assert by_name["__folder__"].label == "Новая папка"
    assert isinstance(by_name["01_Заставка"], MenuNode)      # folder -> submenu
    preset = by_name["02_Зал.json"]
    assert isinstance(preset, ActionNode) and preset.after == After.TEXT
    assert preset.on_press() == "OK 1/1"                      # apply via probe
    assert seen and seen[0]["path"] == "/s"
