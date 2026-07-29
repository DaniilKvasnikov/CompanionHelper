"""Core logic: turn a button press into an action and re-render the deck."""
from __future__ import annotations

import logging

from . import loader, render, state
from .config import COLORS, FEEDBACK_TIMEOUT, SCRIPT_TIMEOUT
from .constants import After, Kind
from .layout import build_layout
from .model import ActionNode, MenuNode
from .runner import run_script

log = logging.getLogger("dispatcher")

# The tree is loaded once and rebuilt on /reload.
_tree: MenuNode = loader.load_tree()


def reload_tree() -> None:
    global _tree
    from . import aoto, pcbrowser

    pcbrowser.refresh_catalog()  # re-read packages / target lists from the DB
    aoto.refresh()               # re-read Aoto groups / commands from disk
    _tree = loader.load_tree()
    log.info("menu tree reloaded")


def render_all_pages() -> None:
    """Redraw every active page (used when ping status changes)."""
    for page in state.all_pages():
        render_page(page)


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
            (cell, slot) for cell, slot in cells.items() if slot.kind == Kind.FEEDBACK
        ]
    for (row, col), slot in feedback_slots:
        res = run_script(slot.node.path, FEEDBACK_TIMEOUT)
        line = res.first_line() if res.ok else "ERR"
        text = f"{slot.label}\n{line}"
        st.feedback_values[slot.node.key] = text
        bg, fg = COLORS[Kind.FEEDBACK]
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
        node = slot.node
        kind = slot.kind
        nav = None

        if kind == Kind.BACK and st.path:
            st.path.pop()
            st.page_index = 0
            nav = "render"
        elif kind == Kind.PREV:
            st.page_index = max(0, st.page_index - 1)
            nav = "render"
        elif kind == Kind.NEXT:
            st.page_index = min(pages - 1, st.page_index + 1)
            nav = "render"
        elif isinstance(node, MenuNode):  # drill into a submenu (static or dynamic)
            st.path.append(node.name)
            st.page_index = 0
            nav = "enter"

    if nav == "render":
        render_page(page)
        return
    if nav == "enter":
        render_page(page)
        refresh_feedback(page)
        return

    # A button press: dynamic ActionNode, or a file-backed CommandNode.
    if isinstance(node, ActionNode):
        _run_action(page, st, row, col, node)
    else:
        _run_command(page, st, row, col, slot, node)


def _run_action(page, st, row, col, node: ActionNode) -> None:
    try:
        text = node.on_press() or ""
    except Exception as e:  # noqa: BLE001
        text = f"ERR\n{e}"
    if node.after == After.BACK:
        with state.lock:
            if st.path:
                st.path.pop()
                st.page_index = 0
        render_page(page)
        refresh_feedback(page)
    elif node.after == After.RERENDER:
        render_page(page)
        refresh_feedback(page)
    else:  # After.TEXT -> show the result on this button
        label = f"{node.label}\n{text}" if text else node.label
        bg, fg = (node.color_fn() if node.color_fn else None) or COLORS.get(node.kind, COLORS[Kind.COMMAND])
        render.update_cell(page, st, row, col, label, bg, fg)


def _run_command(page, st, row, col, slot, node) -> None:
    timeout = FEEDBACK_TIMEOUT if slot.kind == Kind.FEEDBACK else SCRIPT_TIMEOUT
    res = run_script(node.path, timeout)
    text = f"{slot.label}\n{res.summary()}"
    if slot.kind == Kind.FEEDBACK:
        st.feedback_values[node.key] = text
        bg, fg = COLORS[Kind.FEEDBACK]
    else:
        bg, fg = COLORS[Kind.COMMAND] if res.ok else COLORS[Kind.BACK]
    render.update_cell(page, st, row, col, text, bg, fg)
    log.info("ran %s -> code=%s", node.path.name, res.code)
