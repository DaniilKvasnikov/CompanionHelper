"""touch: catalog loading, the group/button menu tree, and the OSC file trigger.

Real OSC is faked by monkeypatching osc.send_to; disk is used only for the
catalog-loading tests via tmp files.
"""
import pytest

from core import touch
from core.config import TOUCH_COMMANDS, TOUCH_OSC_ADDRESS, TOUCH_OSC_HOST, TOUCH_OSC_PORT
from core.constants import After, Kind
from core.model import ActionNode, MenuNode
from core.touch import _Group


@pytest.fixture
def catalog(monkeypatch):
    """In-memory groups, no disk or network."""
    groups = {
        "Стена": _Group(address="/wall", buttons=[("Intro", "intro.tox"), ("Клип A", "clipA.mov")]),
        "Потолок": _Group(address="/ceiling", buttons=[("Звёзды", "stars.mov")]),
    }
    monkeypatch.setattr(touch, "_groups", dict(groups))
    return {"groups": groups}


# --- catalog loading (disk) -----------------------------------------------
def test_load_groups_parses_label_file_comments_and_prefix(tmp_path, monkeypatch):
    d = tmp_path / "groups"
    d.mkdir()
    (d / "01_Стена.txt").write_text(
        "# a comment\n@address = /wall\nIntro = intro.tox\n\nКлип A = clipA.mov  # inline\nbad line\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(touch, "TOUCH_GROUPS_DIR", d)
    out = touch._load_groups()
    # NN_ prefix stripped; @address captured; "bad line" (no '=') skipped
    assert list(out) == ["Стена"]
    assert out["Стена"].address == "/wall"
    assert out["Стена"].buttons == [("Intro", "intro.tox"), ("Клип A", "clipA.mov")]


def test_load_groups_without_address_uses_default(tmp_path, monkeypatch):
    d = tmp_path / "groups"
    d.mkdir()
    (d / "Потолок.txt").write_text("Звёзды = stars.mov\n", encoding="utf-8")
    monkeypatch.setattr(touch, "TOUCH_GROUPS_DIR", d)
    out = touch._load_groups()
    assert out["Потолок"].address == TOUCH_OSC_ADDRESS   # no @address -> config default


def test_load_groups_missing_dir_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(touch, "TOUCH_GROUPS_DIR", tmp_path / "nope")
    assert touch._load_groups() == {}


# --- OSC send -------------------------------------------------------------
def test_send_file_fires_osc_to_the_given_address(monkeypatch):
    sent = []
    monkeypatch.setattr(touch.osc, "send_to", lambda *a: sent.append(a))
    assert touch.send_file("/wall", "clipA.mov") == "OK"
    assert sent == [(TOUCH_OSC_HOST, TOUCH_OSC_PORT, "/wall", "clipA.mov")]


def test_send_command_fires_no_argument_osc_to_named_address(monkeypatch):
    sent = []
    monkeypatch.setattr(touch.osc, "send_to", lambda *a: sent.append(a))
    assert touch.send_command("fps") == "OK"
    assert sent == [(TOUCH_OSC_HOST, TOUCH_OSC_PORT, "/fps")]   # address only, no args


# --- menu tree ------------------------------------------------------------
def test_attach_inserts_after_pc_pdq_aoto():
    root = MenuNode("", None, "", children=[
        MenuNode("__pc__", None, "ПК"), MenuNode("__pdq__", None, "PDQ"),
        MenuNode("__aoto__", None, "AOTO"), MenuNode("other", None, "Other")])
    touch.attach(root)
    assert [c.name for c in root.children] == [
        "__pc__", "__pdq__", "__aoto__", "__touch__", "other"]


def test_attach_at_top_when_no_tabs():
    root = MenuNode("", None, "", children=[MenuNode("other", None, "Other")])
    touch.attach(root)
    assert root.children[0].name == "__touch__"


def test_touch_children_lists_commands_then_groups(catalog):
    kids = touch._touch_children(None)
    assert [k.name for k in kids] == [*TOUCH_COMMANDS, "Стена", "Потолок"]
    # the leading TOUCH_COMMANDS are no-arg ActionNodes; the rest are group menus
    cmds, menus = kids[:len(TOUCH_COMMANDS)], kids[len(TOUCH_COMMANDS):]
    assert all(isinstance(k, ActionNode) for k in cmds)
    assert all(isinstance(k, MenuNode) and k.context.get("group") for k in menus)


def test_touch_command_press_fires_no_arg_osc(catalog, monkeypatch):
    sent = []
    monkeypatch.setattr(touch.osc, "send_to", lambda *a: sent.append(a))
    kids = touch._touch_children(None)
    kids[0].on_press()                       # first command, e.g. "file"
    assert sent == [(TOUCH_OSC_HOST, TOUCH_OSC_PORT, f"/{TOUCH_COMMANDS[0]}")]


def test_group_buttons_builds_action_nodes(catalog):
    node = MenuNode("Стена", None, "Стена", context={"group": "Стена"})
    btns = touch._group_buttons(node)
    assert [b.name for b in btns] == ["Intro", "Клип A"]
    assert all(isinstance(b, ActionNode) and b.after == After.TEXT and b.kind == Kind.COMMAND
               for b in btns)


def test_button_press_sends_to_its_groups_address(catalog, monkeypatch):
    sent = []
    monkeypatch.setattr(touch.osc, "send_to", lambda *a: sent.append(a))
    # Стена -> /wall, Потолок -> /ceiling: each group's buttons use its own address
    touch._group_buttons(MenuNode("Стена", None, "Стена", context={"group": "Стена"}))[1].on_press()
    touch._group_buttons(MenuNode("Потолок", None, "Потолок", context={"group": "Потолок"}))[0].on_press()
    assert sent[0][2:] == ("/wall", "clipA.mov")
    assert sent[1][2:] == ("/ceiling", "stars.mov")
