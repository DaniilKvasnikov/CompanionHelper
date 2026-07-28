"""make_label conventions and children_of (static / provider / error)."""
from pathlib import Path

from core.model import (
    ActionNode,
    CommandNode,
    MenuNode,
    children_of,
    is_feedback,
    is_script,
    make_label,
)


def test_make_label_strips_prefix_extension_and_prettifies():
    assert make_label("01_lights", True) == "Lights"
    assert make_label("01_on.py", False) == "On"
    assert make_label("02_cpu.fb.py", False) == "Cpu"       # .fb dropped too
    assert make_label("03_install.pdq", False) == "Install"
    assert make_label("weird_name-here", True) == "Weird Name Here"


def test_make_label_falls_back_to_raw_when_empty():
    assert make_label("01_", True) == "01_"


def test_is_feedback():
    assert is_feedback(Path("01_cpu.fb.py"))
    assert not is_feedback(Path("01_cpu.py"))


def test_is_script(tmp_path):
    py = tmp_path / "x.py"
    py.write_text("")
    txt = tmp_path / "x.txt"
    txt.write_text("")
    assert is_script(py)
    assert not is_script(txt)


def test_children_of_static():
    leaf = CommandNode("a.py", Path("a.py"), "A")
    menu = MenuNode("m", None, "M", children=[leaf])
    assert children_of(menu) == [leaf]


def test_children_of_provider_is_used_over_children():
    menu = MenuNode("m", None, "M", provider=lambda node: [ActionNode("x", "X", lambda: "")])
    kids = children_of(menu)
    assert len(kids) == 1 and kids[0].name == "x"


def test_children_of_provider_error_yields_err_button():
    def boom(node):
        raise RuntimeError("db down")

    kids = children_of(MenuNode("m", None, "M", provider=boom))
    assert len(kids) == 1 and "ERR" in kids[0].label
