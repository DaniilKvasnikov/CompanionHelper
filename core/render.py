"""Draw a deck page, pushing only what changed and via the cheapest transport.

Per changed cell:
  - text-only change  -> OSC/UDP (fast, no round-trip)      [companion.set_text]
  - color change/new  -> HTTP style (sets text + colors)    [companion.set_style]
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


def _emit(page, st: PageState, row, col, new):
    """Apply one cell's desired style. Returns an HTTP update tuple, or None.

    Text-only changes are sent immediately over OSC and return None; color
    changes (and first draws) are returned so the caller can batch the HTTP
    pushes. Always updates the render cache.
    """
    old = st.rendered.get((row, col))
    if old == new:
        return None
    st.rendered[(row, col)] = new
    if old is not None and old[1] == new[1] and old[2] == new[2]:
        companion.set_text(page, row, col, new[0])  # only text differs
        return None
    return (page, row, col, *new)                    # color changed / first draw


def draw(page: str, cells: dict, st: PageState) -> None:
    """Compute the desired style for all 32 cells; push only the changes."""
    http_updates = []
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            update = _emit(page, st, r, c, _cell_style(cells.get((r, c)), st))
            if update:
                http_updates.append(update)
    if http_updates:
        companion.apply(http_updates)


def update_cell(page: str, st: PageState, row: int, col: int, text, bg, fg) -> None:
    """Push a single button and keep the render cache in sync."""
    update = _emit(page, st, row, col, (text, bg, fg))
    if update:
        companion.set_style(page, row, col, text=text, bgcolor=bg, color=fg)
