"""Draw a deck page, pushing only what changed (all over OSC/UDP).

Per changed cell:
  - text-only change  -> one OSC message  (companion.set_text)
  - color change/new  -> text + bgcolor + color OSC messages (companion.set_style)
"""
from __future__ import annotations

from . import companion
from .config import COLORS, GRID_COLS, GRID_ROWS
from .layout import Slot
from .state import PageState

# Slot.kind -> key into COLORS
_COLOR_KIND = {"back": "back", "prev": "nav", "next": "nav"}
_EMPTY = ("", "#000000", "#000000")


def _colors(kind: str):
    return COLORS.get(_COLOR_KIND.get(kind, kind), COLORS["command"])


def _cell_style(slot: Slot | None, st: PageState):
    if slot is None:
        return _EMPTY
    if slot.kind == "feedback":
        text = st.feedback_values.get(slot.node.key, slot.label)
    else:
        text = slot.label
    bg, fg = _colors(slot.kind)
    return (text, bg, fg)


def _emit(page, st: PageState, row, col, new) -> None:
    """Apply one cell's desired style, cheapest transport first. Updates cache."""
    old = st.rendered.get((row, col))
    if old == new:
        return
    st.rendered[(row, col)] = new
    if old is not None and old[1] == new[1] and old[2] == new[2]:
        companion.set_text(page, row, col, new[0])          # only text differs
    else:
        companion.set_style(page, row, col, *new)           # color changed / new


def draw(page: str, cells: dict, st: PageState) -> None:
    """Compute the desired style for all 32 cells; push only the changes."""
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            _emit(page, st, r, c, _cell_style(cells.get((r, c)), st))


def update_cell(page: str, st: PageState, row: int, col: int, text, bg, fg) -> None:
    """Push a single button and keep the render cache in sync."""
    _emit(page, st, row, col, (text, bg, fg))
