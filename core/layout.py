"""Map a menu's children onto the deck grid.

Content fills rows 0..NAV_ROW-1 in reading order. The bottom row (NAV_ROW) is
reserved for navigation: Back on the left, and Prev/Next on the right when the
menu has more children than fit on one page.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .config import GRID_COLS, NAV_ROW
from .model import ActionNode, CommandNode, MenuNode, children_of

# Cells available for menu items (everything above the nav row).
CONTENT_CELLS = [(r, c) for r in range(NAV_ROW) for c in range(GRID_COLS)]
PER_PAGE = len(CONTENT_CELLS)

BACK_CELL = (NAV_ROW, 0)
PREV_CELL = (NAV_ROW, GRID_COLS - 2)
NEXT_CELL = (NAV_ROW, GRID_COLS - 1)


@dataclass
class Slot:
    kind: str            # menu | command | feedback | back | prev | next
    label: str
    node: object = None  # content node (MenuNode / CommandNode / ActionNode)
    color: tuple | None = None  # (bg, fg) override from a node's color_fn


def _kind(child) -> str:
    if isinstance(child, MenuNode):
        return "menu"
    if isinstance(child, ActionNode):
        return child.kind
    if isinstance(child, CommandNode) and child.feedback:
        return "feedback"
    return "command"


def build_layout(menu: MenuNode, depth: int, page_index: int):
    """Return (cells: dict[(row,col)->Slot], pages: int, page_index: int)."""
    children = children_of(menu)
    pages = max(1, math.ceil(len(children) / PER_PAGE))
    page_index = max(0, min(page_index, pages - 1))

    start = page_index * PER_PAGE
    view = children[start : start + PER_PAGE]

    cells: dict[tuple[int, int], Slot] = {}
    for cell, child in zip(CONTENT_CELLS, view):
        color_fn = getattr(child, "color_fn", None)
        cells[cell] = Slot(
            kind=_kind(child),
            label=child.label,
            node=child,
            color=color_fn() if color_fn else None,
        )

    if depth > 0:
        cells[BACK_CELL] = Slot(kind="back", label="Back")
    if page_index > 0:
        cells[PREV_CELL] = Slot(kind="prev", label="< Prev")
    if page_index < pages - 1:
        cells[NEXT_CELL] = Slot(kind="next", label="Next >")

    return cells, pages, page_index
