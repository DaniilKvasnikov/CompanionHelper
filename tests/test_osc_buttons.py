"""osc_buttons: catalog loading, message parsing, the menu tree, and the send.

Real OSC is faked by monkeypatching osc.send_to; disk is used only for the
catalog-loading tests via tmp files.
"""
import pytest

from core import osc_buttons
from core.config import OSC_BUTTONS_HOST, OSC_BUTTONS_PORT
from core.constants import After, Kind
from core.model import ActionNode, MenuNode
from core.osc_buttons import _Button, _Group


@pytest.fixture
def catalog(monkeypatch):
    """In-memory groups, no disk or network."""
    groups = {
        "Grade": _Group(host="127.0.0.1", port=7000, buttons=[
            _Button("Байпас вкл", "/project1/grade/Bypass", (1,)),
            _Button("Позиция", "/project1/geo1/t", (0.5, 0, 0)),
        ]),
        "Wall": _Group(host="10.0.0.5", port=7100, buttons=[
            _Button("Сброс", "/project1/base1/Reset", ()),
        ]),
    }
    monkeypatch.setattr(osc_buttons, "_groups", dict(groups))
    return {"groups": groups}


# --- message parsing -------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("/project1/grade/Bypass 1", ("/project1/grade/Bypass", (1,))),
    ("/project1/geo1/t 0.5 0 0", ("/project1/geo1/t", (0.5, 0, 0))),
    ("/project1/base1/Reset", ("/project1/base1/Reset", ())),
    ("/project1/base1/Mode gamma", ("/project1/base1/Mode", ("gamma",))),
    ('/project1/text1/text "две слова"', ("/project1/text1/text", ("две слова",))),
    ("/a -1.5", ("/a", (-1.5,))),
])
def test_parse_message_types_arguments(text, expected):
    assert osc_buttons._parse_message(text) == expected


@pytest.mark.parametrize("text", ["", "not-an-address 1", 'unbalanced "quote'])
def test_parse_message_rejects_what_has_no_leading_slash(text):
    assert osc_buttons._parse_message(text) is None


def test_typed_keeps_int_and_float_distinct():
    assert isinstance(osc_buttons._typed("1"), int)
    assert isinstance(osc_buttons._typed("1.0"), float)
    assert osc_buttons._typed("on") == "on"


# --- catalog loading (disk) -----------------------------------------------
def test_load_groups_parses_buttons_directives_comments_and_prefix(tmp_path, monkeypatch):
    d = tmp_path / "groups"
    d.mkdir()
    (d / "01_Grade.txt").write_text(
        "# a comment\n"
        "@host = 10.0.0.5\n"
        "@port = 7100\n"
        "Байпас = /project1/grade/Bypass 1  # inline\n"
        "\n"
        "Позиция = /project1/geo1/t 0.5 0 0\n"
        "bad line\n"
        "Не адрес = oops 1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(osc_buttons, "OSC_BUTTONS_GROUPS_DIR", d)
    out = osc_buttons._load_groups()
    assert list(out) == ["Grade"]                     # NN_ prefix stripped
    assert (out["Grade"].host, out["Grade"].port) == ("10.0.0.5", 7100)
    # "bad line" (no '=') and "Не адрес" (no leading /) are both skipped
    assert [(b.label, b.address, b.args) for b in out["Grade"].buttons] == [
        ("Байпас", "/project1/grade/Bypass", (1,)),
        ("Позиция", "/project1/geo1/t", (0.5, 0, 0)),
    ]


def test_load_groups_without_directives_uses_config_defaults(tmp_path, monkeypatch):
    d = tmp_path / "groups"
    d.mkdir()
    (d / "Wall.txt").write_text("Сброс = /project1/base1/Reset\n", encoding="utf-8")
    monkeypatch.setattr(osc_buttons, "OSC_BUTTONS_GROUPS_DIR", d)
    out = osc_buttons._load_groups()
    assert (out["Wall"].host, out["Wall"].port) == (OSC_BUTTONS_HOST, OSC_BUTTONS_PORT)


def test_load_groups_ignores_a_non_numeric_port(tmp_path, monkeypatch):
    d = tmp_path / "groups"
    d.mkdir()
    (d / "Wall.txt").write_text("@port = nope\nA = /a 1\n", encoding="utf-8")
    monkeypatch.setattr(osc_buttons, "OSC_BUTTONS_GROUPS_DIR", d)
    assert osc_buttons._load_groups()["Wall"].port == OSC_BUTTONS_PORT


def test_load_groups_missing_dir_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(osc_buttons, "OSC_BUTTONS_GROUPS_DIR", tmp_path / "nope")
    assert osc_buttons._load_groups() == {}


# --- OSC send -------------------------------------------------------------
def test_send_fires_address_and_args(monkeypatch):
    sent = []
    monkeypatch.setattr(osc_buttons.osc, "send_to", lambda *a: sent.append(a))
    assert osc_buttons.send("10.0.0.5", 7100, "/project1/geo1/t", (0.5, 0, 0)) == "OK"
    assert sent == [("10.0.0.5", 7100, "/project1/geo1/t", 0.5, 0, 0)]


def test_send_without_args_is_address_only(monkeypatch):
    sent = []
    monkeypatch.setattr(osc_buttons.osc, "send_to", lambda *a: sent.append(a))
    osc_buttons.send("127.0.0.1", 7000, "/project1/base1/Reset")
    assert sent == [("127.0.0.1", 7000, "/project1/base1/Reset")]


# --- menu tree ------------------------------------------------------------
def test_attach_inserts_after_pc_pdq_aoto_touch():
    root = MenuNode("", None, "", children=[
        MenuNode("__pc__", None, "ПК"), MenuNode("__pdq__", None, "PDQ"),
        MenuNode("__aoto__", None, "AOTO"), MenuNode("__touch__", None, "Touch"),
        MenuNode("other", None, "Other")])
    osc_buttons.attach(root)
    assert [c.name for c in root.children] == [
        "__pc__", "__pdq__", "__aoto__", "__touch__", "__osc__", "other"]


def test_attach_at_top_when_no_tabs():
    root = MenuNode("", None, "", children=[MenuNode("other", None, "Other")])
    osc_buttons.attach(root)
    assert root.children[0].name == "__osc__"


def test_osc_children_lists_the_groups(catalog):
    kids = osc_buttons._osc_children(None)
    assert [k.name for k in kids] == ["Grade", "Wall"]
    assert all(isinstance(k, MenuNode) and k.context.get("group") for k in kids)


def test_group_buttons_builds_action_nodes(catalog):
    node = MenuNode("Grade", None, "Grade", context={"group": "Grade"})
    btns = osc_buttons._group_buttons(node)
    assert [b.name for b in btns] == ["Байпас вкл", "Позиция"]
    assert all(isinstance(b, ActionNode) and b.after == After.TEXT and b.kind == Kind.COMMAND
               for b in btns)


def test_button_press_sends_its_own_address_args_and_target(catalog, monkeypatch):
    sent = []
    monkeypatch.setattr(osc_buttons.osc, "send_to", lambda *a: sent.append(a))
    # each button carries its own address+args; each group its own host:port
    osc_buttons._group_buttons(MenuNode("Grade", None, "", context={"group": "Grade"}))[1].on_press()
    osc_buttons._group_buttons(MenuNode("Wall", None, "", context={"group": "Wall"}))[0].on_press()
    assert sent[0] == ("127.0.0.1", 7000, "/project1/geo1/t", 0.5, 0, 0)
    assert sent[1] == ("10.0.0.5", 7100, "/project1/base1/Reset")
