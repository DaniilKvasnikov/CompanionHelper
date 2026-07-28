"""build_layout: kind detection, nav row, pagination, clamping, color."""
from pathlib import Path

from core.constants import Kind
from core.layout import (
    BACK_CELL,
    NEXT_CELL,
    PER_PAGE,
    PREV_CELL,
    Slot,
    build_layout,
)
from core.model import ActionNode, CommandNode, MenuNode


def cmd(name, feedback=False):
    return CommandNode(name, Path(name), name, feedback=feedback)


def menu(children, **kw):
    return MenuNode("root", None, "", children=children, **kw)


def test_kind_detection_by_node_type():
    m = menu([
        MenuNode("sub", None, "Sub"),
        cmd("c"),
        cmd("f", feedback=True),
        ActionNode("a", "A", lambda: "", kind=Kind.COMMAND),
    ])
    cells, _, _ = build_layout(m, depth=0, page_index=0)
    assert cells[(0, 0)].kind == Kind.MENU
    assert cells[(0, 1)].kind == Kind.COMMAND
    assert cells[(0, 2)].kind == Kind.FEEDBACK
    assert cells[(0, 3)].kind == Kind.COMMAND


def test_no_back_button_at_root():
    cells, _, _ = build_layout(menu([cmd("c")]), depth=0, page_index=0)
    assert BACK_CELL not in cells


def test_back_button_when_nested():
    cells, _, _ = build_layout(menu([cmd("c")]), depth=1, page_index=0)
    assert cells[BACK_CELL].kind == Kind.BACK


def test_pagination_prev_next_and_counts():
    m = menu([cmd(str(i)) for i in range(PER_PAGE + 5)])  # two pages

    cells, pages, pi = build_layout(m, depth=0, page_index=0)
    assert pages == 2 and pi == 0
    assert NEXT_CELL in cells and PREV_CELL not in cells

    cells, pages, pi = build_layout(m, depth=0, page_index=1)
    assert PREV_CELL in cells and NEXT_CELL not in cells
    content = [c for c in cells if c[0] < 3]  # rows above the nav row
    assert len(content) == 5


def test_page_index_is_clamped():
    _, pages, pi = build_layout(menu([cmd("c")]), depth=0, page_index=99)
    assert pages == 1 and pi == 0


def test_color_fn_overrides_slot_color():
    m = menu([MenuNode("pc", None, "PC", color_fn=lambda: ("#111111", "#222222"))])
    cells, _, _ = build_layout(m, depth=0, page_index=0)
    assert cells[(0, 0)].color == ("#111111", "#222222")


def test_slot_without_color_fn_has_none():
    cells, _, _ = build_layout(menu([cmd("c")]), depth=0, page_index=0)
    assert cells[(0, 0)].color is None
    assert isinstance(cells[(0, 0)], Slot)
