"""Press dispatch: drill-in, ActionNode after-behavior, provider navigation."""
from pathlib import Path

import pytest

from core import companion, dispatcher, state
from core.constants import After, Kind
from core.model import ActionNode, CommandNode, MenuNode
from core.runner import RunResult


@pytest.fixture
def quiet(monkeypatch):
    """No real OSC and a clean per-test page-state table."""
    monkeypatch.setattr(companion, "set_text", lambda *a, **k: None)
    monkeypatch.setattr(companion, "set_style", lambda *a, **k: None)
    state._states.clear()
    yield
    state._states.clear()


def set_tree(monkeypatch, root):
    monkeypatch.setattr(dispatcher, "_tree", root)


def test_menu_press_drills_in(quiet, monkeypatch):
    root = MenuNode("", None, "", children=[MenuNode("sub", None, "Sub")])
    set_tree(monkeypatch, root)
    dispatcher.handle_press("1", 0, 0)
    assert state.get_state("1").path == ["sub"]


def test_action_after_back_runs_then_pops(quiet, monkeypatch):
    fired = []
    action = ActionNode("x", "X", on_press=lambda: fired.append(1) or "", after=After.BACK)
    root = MenuNode("", None, "", children=[MenuNode("sub", None, "Sub", children=[action])])
    set_tree(monkeypatch, root)

    dispatcher.handle_press("1", 0, 0)          # into sub
    assert state.get_state("1").path == ["sub"]
    dispatcher.handle_press("1", 0, 0)          # press action -> back
    assert fired == [1]
    assert state.get_state("1").path == []


def test_command_node_runs_script(quiet, monkeypatch):
    calls = []
    monkeypatch.setattr(
        dispatcher, "run_script",
        lambda path, timeout: calls.append(path) or RunResult(0, "done", ""),
    )
    root = MenuNode("", None, "", children=[CommandNode("c.py", Path("c.py"), "C")])
    set_tree(monkeypatch, root)
    dispatcher.handle_press("1", 0, 0)
    assert calls == [Path("c.py")]


def test_provider_menu_navigation_two_levels(quiet, monkeypatch):
    inner = lambda node: [ActionNode(node.context["v"], node.context["v"], lambda: "")]

    def outer(node):
        return [MenuNode("item", None, "Item", provider=inner, context={"v": "deep"})]

    root = MenuNode("", None, "", children=[MenuNode("dyn", None, "Dyn", provider=outer)])
    set_tree(monkeypatch, root)

    dispatcher.handle_press("1", 0, 0)          # into dynamic menu
    assert state.get_state("1").path == ["dyn"]
    dispatcher.handle_press("1", 0, 0)          # into provider-produced submenu
    assert state.get_state("1").path == ["dyn", "item"]


def test_prev_next_paging(quiet, monkeypatch):
    from core.layout import NEXT_CELL, PER_PAGE, PREV_CELL

    children = [CommandNode(f"{i}.py", Path(f"{i}.py"), str(i)) for i in range(PER_PAGE + 3)]
    set_tree(monkeypatch, MenuNode("", None, "", children=children))

    dispatcher.handle_press("1", *NEXT_CELL)
    assert state.get_state("1").page_index == 1
    dispatcher.handle_press("1", *PREV_CELL)
    assert state.get_state("1").page_index == 0
