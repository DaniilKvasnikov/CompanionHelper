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
    monkeypatch.setattr(pcbrowser, "_aliases", {})
    monkeypatch.setattr(pcbrowser, "_load_aliases", lambda: {})  # no disk in catalog tests
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


# --- PC aliases -----------------------------------------------------------
def test_load_aliases_parses_pairs_and_skips_junk(tmp_path, monkeypatch):
    f = tmp_path / "pc_aliases.txt"
    f.write_text(
        "# comment\n192.168.0.5 = Reception\n\nno-equals-line\n192.168.0.6=Studio A  # inline\n",
        encoding="utf-8")
    monkeypatch.setattr(pcbrowser, "PC_ALIASES_FILE", f)
    assert pcbrowser._load_aliases() == {"192.168.0.5": "Reception", "192.168.0.6": "Studio A"}


def test_load_aliases_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(pcbrowser, "PC_ALIASES_FILE", tmp_path / "nope.txt")
    assert pcbrowser._load_aliases() == {}


def test_host_label_shows_alias_above_ip(monkeypatch):
    monkeypatch.setattr(pcbrowser, "_aliases", {"192.168.0.5": "Reception"})
    assert pcbrowser.host_label("192.168.0.5") == "Reception\n192.168.0.5"
    assert pcbrowser.host_label("192.168.0.9") == "192.168.0.9"   # no alias -> raw host


def test_members_sorted_aliased_first_then_by_host(monkeypatch):
    monkeypatch.setattr(pcbrowser, "_lists", ["L"])
    monkeypatch.setattr(pcbrowser, "_active_list", "L")
    monkeypatch.setattr(pcbrowser, "_members", {"L": ["192.168.0.9", "192.168.0.5", "192.168.0.7"]})
    monkeypatch.setattr(pcbrowser, "_aliases", {"192.168.0.7": "Alpha", "192.168.0.5": "Zeta"})
    # aliased first by alias (Alpha < Zeta), then unaliased hosts by ip
    assert pcbrowser.members() == ["192.168.0.7", "192.168.0.5", "192.168.0.9"]


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
    picker = pcbrowser.list_picker(None)
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
