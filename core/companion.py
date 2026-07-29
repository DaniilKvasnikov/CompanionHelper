"""Facade for updating button visuals in Companion, all over OSC/UDP.

Everything is fire-and-forget (no round-trip), so redrawing is fast and there
is nothing to wait on. Colors are sent as r/g/b 0-255. render.py decides which
of these to call based on what actually changed.
"""
from __future__ import annotations

from . import osc


def _rgb(color: str) -> tuple[int, int, int]:
    """'#12233b' -> (18, 35, 59)."""
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def set_text(page, row, col, text: str) -> None:
    osc.set_text(page, row, col, text)


def set_style(page, row, col, text="", bgcolor="#000000", color="#ffffff") -> None:
    osc.set_text(page, row, col, text)
    osc.set_bgcolor(page, row, col, *_rgb(bgcolor))
    osc.set_color(page, row, col, *_rgb(color))


def clear(page, row, col) -> None:
    set_style(page, row, col, text="", bgcolor="#000000", color="#000000")


def set_custom_variable(name: str, value: str) -> None:
    """Set a Companion custom variable. Global, so it bypasses the cell diff."""
    osc.set_custom_variable(name, value)
