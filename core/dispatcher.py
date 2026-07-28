"""Core logic: turn a button press into an action and re-render the deck."""
from __future__ import annotations

import logging

from . import loader, render, state
from .config import COLORS, FEEDBACK_TIMEOUT, SCRIPT_TIMEOUT
from .layout import build_layout
from .model import MenuNode
from .runner import run_script

log = logging.getLogger("dispatcher")

# The tree is loaded once and rebuilt on /reload.
_tree: MenuNode = loader.load_tree()


def reload_tree() -> None:
    global _tree
    _tree = loader.load_tree()
    log.info("menu tree reloaded from %s", _tree.path)


def _menu_for(st) -> MenuNode:
    return loader.resolve(_tree, st.path)


def render_page(page: str) -> None:
    """Draw the current menu for `page` (creating its state if needed)."""
    st = state.get_state(page)
    with state.lock:
        menu = _menu_for(st)
        cells, pages, page_index = build_layout(menu, len(st.path), st.page_index)
        st.pages, st.page_index = pages, page_index
    render.draw(page, cells, st)


def refresh_feedback(page: str) -> None:
    """Run the visible feedback scripts for `page` and update their buttons."""
    st = state.get_state(page)
    with state.lock:
        menu = _menu_for(st)
        cells, _, _ = build_layout(menu, len(st.path), st.page_index)
        feedback_slots = [
            (cell, slot) for cell, slot in cells.items() if slot.kind == "feedback"
        ]
    for (row, col), slot in feedback_slots:
        res = run_script(slot.node.path, FEEDBACK_TIMEOUT)
        line = res.first_line() if res.ok else "ERR"
        text = f"{slot.label}\n{line}"
        st.feedback_values[slot.node.key] = text
        bg, fg = COLORS["feedback"]
        render.update_cell(page, st, row, col, text, bg, fg)


def handle_press(page: str, row: int, col: int) -> None:
    st = state.get_state(page)
    with state.lock:
        menu = _menu_for(st)
        cells, pages, st.page_index = build_layout(menu, len(st.path), st.page_index)
        st.pages = pages
        slot = cells.get((row, col))
        if slot is None:
            return
        kind = slot.kind

        if kind == "back" and st.path:
            st.path.pop()
            st.page_index = 0
        elif kind == "prev":
            st.page_index = max(0, st.page_index - 1)
        elif kind == "next":
            st.page_index = min(pages - 1, st.page_index + 1)
        elif kind == "menu":
            st.path.append(slot.node.name)
            st.page_index = 0

    # Navigation -> redraw the whole page (+ prime feedback on the new menu).
    if kind in ("back", "prev", "next", "menu"):
        render_page(page)
        if kind in ("back", "menu"):
            refresh_feedback(page)
        return

    # Command / feedback press -> run it and show the result on that button.
    node = slot.node
    timeout = FEEDBACK_TIMEOUT if kind == "feedback" else SCRIPT_TIMEOUT
    res = run_script(node.path, timeout)
    line = res.first_line() or ("OK" if res.ok else "ERR")
    if kind == "feedback":
        text = f"{slot.label}\n{line}"
        st.feedback_values[node.key] = text
        bg, fg = COLORS["feedback"]
    else:
        text = f"{slot.label}\n{line}"
        bg, fg = COLORS["command"] if res.ok else COLORS["back"]
    render.update_cell(page, st, row, col, text, bg, fg)
    log.info("ran %s -> code=%s", node.path.name, res.code)
