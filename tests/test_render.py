"""render diffing + transport selection (OSC text vs full style)."""
import pytest

from core import companion, render
from core.constants import Kind
from core.layout import Slot
from core.state import PageState


class Spy:
    def __init__(self):
        self.text = []
        self.style = []


@pytest.fixture
def spy(monkeypatch):
    s = Spy()
    monkeypatch.setattr(companion, "set_text", lambda p, r, c, t: s.text.append((r, c, t)))
    monkeypatch.setattr(
        companion,
        "set_style",
        lambda p, r, c, text="", bgcolor="", color="": s.style.append((r, c, text, bgcolor, color)),
    )
    return s


def test_new_cell_uses_full_style(spy):
    render.update_cell("1", PageState(), 0, 0, "A", "#111111", "#222222")
    assert len(spy.style) == 1 and spy.text == []


def test_unchanged_cell_pushes_nothing(spy):
    st = PageState()
    render.update_cell("1", st, 0, 0, "A", "#111111", "#222222")
    spy.style.clear()
    render.update_cell("1", st, 0, 0, "A", "#111111", "#222222")
    assert spy.style == [] and spy.text == []


def test_text_only_change_uses_osc(spy):
    st = PageState()
    render.update_cell("1", st, 0, 0, "A", "#111111", "#222222")
    spy.style.clear()
    render.update_cell("1", st, 0, 0, "B", "#111111", "#222222")
    assert len(spy.text) == 1 and spy.style == []


def test_color_change_uses_full_style(spy):
    st = PageState()
    render.update_cell("1", st, 0, 0, "A", "#111111", "#222222")
    spy.style.clear()
    spy.text.clear()
    render.update_cell("1", st, 0, 0, "A", "#333333", "#222222")
    assert len(spy.style) == 1 and spy.text == []


def test_draw_styles_all_cells_first_then_diffs(spy):
    st = PageState()
    cells = {(0, 0): Slot(kind=Kind.COMMAND, label="X", node=None)}
    render.draw("1", cells, st)
    assert len(spy.style) == 32  # 1 content + 31 cleared empties, all new

    spy.style.clear()
    spy.text.clear()
    render.draw("1", cells, st)  # nothing changed
    assert spy.style == [] and spy.text == []
