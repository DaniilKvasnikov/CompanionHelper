"""pcbrowser: catalog cache, active-list selection, ping color, provider tree."""
import pytest

from core import pcbrowser, pdq
from core.constants import After, Kind
from core.model import ActionNode, MenuNode


@pytest.fixture
def catalog(monkeypatch):
    """Fake the DB layer and reset the module's caches to a clean slate."""
    data = {
        "lists": ["Office", "Lab"],
        "packages": ["Chrome", "7-Zip"],
        "members": {"Office": ["PC-A", "PC-B"], "Lab": ["PC-C"]},
    }
    monkeypatch.setattr(pdq, "list_target_lists", lambda: list(data["lists"]))
    monkeypatch.setattr(pdq, "list_packages", lambda: list(data["packages"]))
    monkeypatch.setattr(pdq, "target_list_members", lambda name: list(data["members"].get(name, [])))

    monkeypatch.setattr(pcbrowser, "_active_list", None)
    monkeypatch.setattr(pcbrowser, "_lists", [])
    monkeypatch.setattr(pcbrowser, "_packages", [])
    monkeypatch.setattr(pcbrowser, "_members", {})
    monkeypatch.setattr(pcbrowser, "_ping", {})
    return data


def test_refresh_catalog_caches_lists_packages_members(catalog):
    pcbrowser.refresh_catalog()
    assert pcbrowser.lists() == ["Office", "Lab"]
    assert pcbrowser.packages() == ["Chrome", "7-Zip"]
    assert pcbrowser.members() == ["PC-A", "PC-B"]  # active defaults to first list


def test_active_list_defaults_to_first(catalog):
    pcbrowser.refresh_catalog()
    assert pcbrowser.active_list() == "Office"


def test_set_active_switches_list_and_members(catalog):
    pcbrowser.refresh_catalog()
    pcbrowser.set_active("Lab")
    assert pcbrowser.active_list() == "Lab"
    assert pcbrowser.members() == ["PC-C"]


def test_active_list_ignores_unknown_selection(catalog):
    pcbrowser.refresh_catalog()
    pcbrowser.set_active("Ghost")  # not among known lists
    assert pcbrowser.active_list() == "Office"  # falls back to first


def test_pc_color_reflects_ping_state(catalog):
    from core.config import PC_DOWN, PC_UNKNOWN, PC_UP

    pcbrowser._ping.update({"PC-A": True, "PC-B": False})
    assert pcbrowser.pc_color("PC-A") == PC_UP
    assert pcbrowser.pc_color("PC-B") == PC_DOWN
    assert pcbrowser.pc_color("PC-Z") == PC_UNKNOWN  # never pinged


def test_attach_inserts_pc_menu_at_top():
    root = MenuNode("", None, "", children=[MenuNode("other", None, "Other")])
    pcbrowser.attach(root)
    assert root.children[0].name == "__pc__"
    assert root.children[0].label == "ПК"


def test_pc_children_has_changelist_then_hosts(catalog):
    pcbrowser.refresh_catalog()
    kids = pcbrowser._pc_children(None)
    assert kids[0].name == "__changelist__"
    assert kids[0].label == "Лист:\nOffice"
    assert [k.name for k in kids[1:]] == ["PC-A", "PC-B"]
    assert kids[1].context == {"host": "PC-A"}  # host carried into the package menu


def test_list_picker_marks_active_and_selects(catalog):
    pcbrowser.refresh_catalog()
    picker = pcbrowser._list_picker(None)
    labels = {p.name: p.label for p in picker}
    assert labels["Office"] == "* Office"  # active marked with a star
    assert labels["Lab"] == "Lab"
    assert all(isinstance(p, ActionNode) and p.after == After.BACK for p in picker)

    lab = next(p for p in picker if p.name == "Lab")
    lab.on_press()  # picking a list activates it
    assert pcbrowser.active_list() == "Lab"


def test_pc_packages_deploys_to_single_host(catalog, monkeypatch):
    pcbrowser.refresh_catalog()
    captured = {}

    def fake_run(args, timeout=None):
        captured["args"] = args
        return (0, "started", "")

    monkeypatch.setattr(pdq, "run", fake_run)

    node = MenuNode("PC-A", None, "PC-A", context={"host": "PC-A"})
    pkgs = pcbrowser._pc_packages(node)
    assert [p.name for p in pkgs] == ["Chrome", "7-Zip"]
    assert all(p.kind == Kind.COMMAND for p in pkgs)

    msg = pkgs[0].on_press()  # deploy Chrome to PC-A only
    assert captured["args"] == ["Deploy", "-Package", "Chrome", "-Targets", "PC-A"]
    assert msg == "started"
