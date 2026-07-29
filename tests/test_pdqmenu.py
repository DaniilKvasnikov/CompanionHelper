"""pdqmenu: enable/disable + scope state, and the PDQ batch menu tree.

The pcbrowser catalog (active list / members / packages / ping) is faked; only
pdqmenu's own state (_disabled per list, _scope_active) is exercised for real.
"""
import pytest

from core import pcbrowser, pdq, pdqmenu
from core.config import PC_DOWN, PC_OFF, PC_UNKNOWN, PC_UP
from core.constants import After, Kind
from core.model import ActionNode, MenuNode


@pytest.fixture
def catalog(monkeypatch):
    st = {
        "active": "Office",
        "members": {"Office": ["PC-A", "PC-B", "PC-C"], "Lab": ["PC-X"]},
        "packages": ["Chrome", "7-Zip"],
        "ping": {"PC-A": True, "PC-B": False},   # PC-C never pinged
    }
    monkeypatch.setattr(pcbrowser, "active_list", lambda: st["active"])
    monkeypatch.setattr(pcbrowser, "members", lambda: list(st["members"].get(st["active"], [])))
    monkeypatch.setattr(pcbrowser, "packages", lambda: list(st["packages"]))

    def pc_color(h):
        s = st["ping"].get(h)
        return PC_UP if s is True else PC_DOWN if s is False else PC_UNKNOWN

    monkeypatch.setattr(pcbrowser, "pc_color", pc_color)
    monkeypatch.setattr(pdqmenu, "_disabled", {})
    monkeypatch.setattr(pdqmenu, "_scope_active", False)
    return st


# --- enable/disable + scope state -----------------------------------------
def test_all_hosts_enabled_by_default(catalog):
    assert all(pdqmenu.is_enabled(h) for h in ["PC-A", "PC-B", "PC-C"])


def test_toggle_host_disables_and_reenables(catalog):
    pdqmenu.toggle_host("PC-B")
    assert pdqmenu.is_enabled("PC-B") is False
    pdqmenu.toggle_host("PC-B")
    assert pdqmenu.is_enabled("PC-B") is True


def test_disabled_set_is_per_list(catalog):
    pdqmenu.toggle_host("PC-A")             # disabled in Office
    assert pdqmenu.is_enabled("PC-A") is False
    catalog["active"] = "Lab"
    assert pdqmenu.is_enabled("PC-A") is True   # Lab keeps its own (empty) set
    catalog["active"] = "Office"
    assert pdqmenu.is_enabled("PC-A") is False  # Office still remembers


def test_toggle_scope_flips(catalog):
    assert pdqmenu.scope_active() is False
    pdqmenu.toggle_scope()
    assert pdqmenu.scope_active() is True


def test_targets_whole_list_ignores_disabled(catalog):
    pdqmenu.toggle_host("PC-B")             # off, but scope is whole-list
    assert pdqmenu.targets() == ["PC-A", "PC-B", "PC-C"]


def test_targets_active_scope_excludes_disabled(catalog):
    pdqmenu.toggle_scope()                  # -> active-only
    pdqmenu.toggle_host("PC-B")
    assert pdqmenu.targets() == ["PC-A", "PC-C"]


# --- menu tree -------------------------------------------------------------
def test_attach_inserts_pdq_after_pc():
    root = MenuNode("", None, "", children=[
        MenuNode("__pc__", None, "ПК"), MenuNode("other", None, "Other")])
    pdqmenu.attach(root)
    assert [c.name for c in root.children] == ["__pc__", "__pdq__", "other"]


def test_attach_at_top_when_no_pc_menu():
    root = MenuNode("", None, "", children=[MenuNode("other", None, "Other")])
    pdqmenu.attach(root)
    assert root.children[0].name == "__pdq__"


def test_pdq_children_layout(catalog):
    kids = pdqmenu._pdq_children(None)
    assert [k.name for k in kids[:3]] == ["__pdq_list__", "__pdq_pcs__", "__pdq_scope__"]
    assert kids[0].label == "Лист:\nOffice"
    assert kids[2].label == "Область:\nвесь список"
    assert kids[2].after == After.RERENDER
    assert [k.name for k in kids[3:]] == ["Chrome", "7-Zip"]
    assert all(isinstance(k, ActionNode) and k.after == After.TEXT for k in kids[3:])


def test_scope_button_label_reflects_state(catalog):
    pdqmenu.toggle_scope()
    scope_btn = pdqmenu._pdq_children(None)[2]
    assert scope_btn.label == "Область:\nактивные"


def test_pc_toggle_picker_marks_colors_and_toggles(catalog):
    picker = pdqmenu._pc_toggle_picker(None)
    labels = {p.name: p.label for p in picker}
    assert labels == {"PC-A": "✓ PC-A", "PC-B": "✓ PC-B", "PC-C": "✓ PC-C"}
    assert all(p.after == After.RERENDER for p in picker)
    # enabled hosts keep their ping color; a disabled host goes dim
    assert picker[0].color_fn() == PC_UP           # PC-A up
    picker[0].on_press()                            # toggle PC-A off
    assert pdqmenu.is_enabled("PC-A") is False
    assert pdqmenu._pc_toggle_picker(None)[0].label == "✗ PC-A"
    assert pdqmenu._pc_toggle_picker(None)[0].color_fn() == PC_OFF


def test_deploy_targets_current_scope(catalog, monkeypatch):
    captured = {}

    def fake_run(args, timeout=None):
        captured["args"] = args
        return (0, "queued", "")

    monkeypatch.setattr(pdq, "run", fake_run)
    pdqmenu.toggle_scope()                  # active-only
    pdqmenu.toggle_host("PC-B")             # exclude PC-B

    pkg_btn = pdqmenu._pdq_children(None)[3]   # first package (Chrome)
    msg = pkg_btn.on_press()
    assert captured["args"] == ["Deploy", "-Package", "Chrome", "-Targets", "PC-A", "PC-C"]
    assert msg == "queued"


def test_deploy_no_hosts_returns_message(catalog, monkeypatch):
    called = {"run": False}
    monkeypatch.setattr(pdq, "run", lambda *a, **k: called.__setitem__("run", True))
    pdqmenu.toggle_scope()                  # active-only
    for h in ["PC-A", "PC-B", "PC-C"]:
        pdqmenu.toggle_host(h)              # disable everything
    assert pdqmenu._deploy("Chrome") == "нет ПК"
    assert called["run"] is False           # nothing deployed
