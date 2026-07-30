"""touch: catalog loading, the group/button menu tree, and the OSC file trigger.

Real OSC is faked by monkeypatching osc.send_to; disk is used only for the
catalog-loading tests via tmp files.
"""
import pytest

from core import touch
from core.config import TOUCH_OSC_ADDRESS, TOUCH_OSC_HOST, TOUCH_OSC_PORT
from core.constants import After, Kind
from core.model import ActionNode, MenuNode


@pytest.fixture
def catalog(monkeypatch):
    """In-memory groups, no disk or network."""
    groups = {
        "Стена": [("Intro", "intro.tox"), ("Клип A", "clipA.mov")],
        "Потолок": [("Звёзды", "stars.mov")],
    }
    monkeypatch.setattr(touch, "_groups", dict(groups))
    return {"groups": groups}


# --- catalog loading (disk) -----------------------------------------------
def test_load_groups_parses_label_file_comments_and_prefix(tmp_path, monkeypatch):
    d = tmp_path / "groups"
    d.mkdir()
    (d / "01_Стена.txt").write_text(
        "# a comment\nIntro = intro.tox\n\nКлип A = clipA.mov  # inline\nbad line\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(touch, "TOUCH_GROUPS_DIR", d)
    out = touch._load_groups()
    # NN_ prefix stripped; "bad line" (no '=') skipped
    assert out == {"Стена": [("Intro", "intro.tox"), ("Клип A", "clipA.mov")]}


def test_load_groups_missing_dir_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(touch, "TOUCH_GROUPS_DIR", tmp_path / "nope")
    assert touch._load_groups() == {}


# --- OSC send -------------------------------------------------------------
def test_send_file_fires_osc_to_touch_destination(monkeypatch):
    sent = []
    monkeypatch.setattr(touch.osc, "send_to", lambda *a: sent.append(a))
    assert touch.send_file("clipA.mov") == "OK"
    assert sent == [(TOUCH_OSC_HOST, TOUCH_OSC_PORT, TOUCH_OSC_ADDRESS, "clipA.mov")]


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


def test_touch_children_lists_groups(catalog):
    kids = touch._touch_children(None)
    assert [k.name for k in kids] == ["Стена", "Потолок"]
    assert all(isinstance(k, MenuNode) for k in kids)
    assert kids[0].context == {"group": "Стена"}


def test_group_buttons_builds_action_nodes(catalog):
    node = MenuNode("Стена", None, "Стена", context={"group": "Стена"})
    btns = touch._group_buttons(node)
    assert [b.name for b in btns] == ["Intro", "Клип A"]
    assert all(isinstance(b, ActionNode) and b.after == After.TEXT and b.kind == Kind.COMMAND
               for b in btns)


def test_button_press_sends_its_filename(catalog, monkeypatch):
    sent = []
    monkeypatch.setattr(touch.osc, "send_to", lambda *a: sent.append(a))
    node = MenuNode("Стена", None, "Стена", context={"group": "Стена"})
    btns = touch._group_buttons(node)
    assert btns[1].on_press() == "OK"                 # "Клип A"
    assert sent[0][3] == "clipA.mov"                  # its own filename, not the first button's
