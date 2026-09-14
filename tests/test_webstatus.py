"""webstatus: the read plan, the snapshot, and the page plumbing.

No HTTP, no disk, no tmp files: every source the page reads (aoto, aotopresets,
pcbrowser, pixelhue) is faked through its cache/public seams, so these tests pin
down exactly what the page shows and how often the devices are touched.
"""
import threading
import time

import pytest

from core import aoto, aotopresets, diag, pcbrowser, pixelhue, webstatus
from core.config import WEB_PAGE, WEB_REFRESH_INTERVAL


@pytest.fixture
def world(monkeypatch):
    """A two-group / one-device fake world, plus the page's own state reset."""
    monkeypatch.setattr(webstatus, "_snapshot", {})
    monkeypatch.setattr(webstatus, "_read_at", None)
    monkeypatch.setattr(webstatus, "_viewer_until", 0.0)
    monkeypatch.setattr(webstatus, "_wake", threading.Event())
    monkeypatch.setattr(diag, "_items", {})

    groups = {"Зал1": ["10.0.0.1:8080", "10.0.0.2:8080"], "Зал2": ["10.0.0.3:8080"]}
    monkeypatch.setattr(aoto, "_groups", dict(groups))
    monkeypatch.setattr(aoto, "_group_maxima", {"Зал1": 1500})
    monkeypatch.setattr(aoto, "_commands", [
        {"label": "Яркость", "method": "POST", "path": "/getGlobalSettings", "body": {},
         "response_field": "obj.brightness"},
    ])
    monkeypatch.setattr(aotopresets, "_parameters", [
        {"name": "Яркость",                       # reads the same thing as the status above
         "set": {"path": "/setBrightness", "key": "brightness"},
         "get": {"path": "/getGlobalSettings", "field": "obj.brightness"}},
        {"name": "Гамма",
         "set": {"path": "/setGamma", "key": "gammaCoefficient"},
         "get": {"path": "/getGlobalSettings", "field": "obj.gammaCoefficient"}},
    ])

    replies = {                                  # (group, path) -> {addr: parsed reply}
        ("Зал1", "/getGlobalSettings"): {
            "10.0.0.1:8080": {"obj": {"brightness": 1200, "gammaCoefficient": 2.2}},
            "10.0.0.2:8080": {"obj": {"brightness": 1200, "gammaCoefficient": 2.2}}},
        ("Зал2", "/getGlobalSettings"): {
            "10.0.0.3:8080": {"obj": {"brightness": 300, "gammaCoefficient": 2.4}}},
    }
    reads: list[tuple] = []

    def fake_probe_raw(group, cmd):
        reads.append((group, cmd["method"], cmd["path"], cmd.get("body")))
        table = replies.get((group, cmd["path"]), {})
        return [(addr, addr in table, table.get(addr)) for addr in aoto.addresses(group)]

    monkeypatch.setattr(aoto, "probe_raw", fake_probe_raw)

    pulls: list[int] = []
    monkeypatch.setattr(pixelhue, "refresh_now", lambda: pulls.append(1))
    monkeypatch.setattr(pixelhue, "_node", {"online": 1, "version": "Q8 V1.0"})
    monkeypatch.setattr(pixelhue, "_last_err", None)
    monkeypatch.setattr(pixelhue, "_mapping", 1)
    monkeypatch.setattr(pixelhue, "_screens", [pixelhue.Screen(6, "g6", "Экран 1", 0, 1),
                                               pixelhue.Screen(7, "g7", "Экран 2", 0, 0)])
    monkeypatch.setattr(pixelhue, "_presets", [pixelhue.Preset("p1", "Ночь", 1)])

    monkeypatch.setattr(pcbrowser, "_lists", ["Зал"])
    monkeypatch.setattr(pcbrowser, "_active_list", "Зал")
    monkeypatch.setattr(pcbrowser, "_members", {"Зал": ["10.0.0.9", "10.0.0.5"]})
    monkeypatch.setattr(pcbrowser, "_aliases", {"10.0.0.5": "Режиссёрская"})
    monkeypatch.setattr(pcbrowser, "_ping", {"10.0.0.9": True, "10.0.0.5": False})
    monkeypatch.setattr(pcbrowser, "_ping_at", None)

    return {"groups": groups, "replies": replies, "reads": reads, "pulls": pulls}


def _params(snapshot, group):
    return {p["label"]: p for g in snapshot["aoto"] if g["group"] == group for p in g["params"]}


# --- read plan --------------------------------------------------------------
def test_read_specs_keeps_deck_labels_and_drops_duplicate_reads(world):
    specs = webstatus.read_specs()
    # "Яркость" comes from commands.json; the identical catalog row is dropped
    assert [s["label"] for s in specs] == ["Яркость", "Гамма"]


def test_body_key_treats_missing_and_empty_body_as_one_request():
    assert webstatus._body_key(None) == webstatus._body_key({})
    assert webstatus._body_key({"id": 1}) != webstatus._body_key({})


def test_reads_are_grouped_by_endpoint(world):
    """Several parameters of one reply cost ONE request per controller."""
    specs = webstatus.read_specs()
    assert len(specs) == 2
    assert len({webstatus._endpoint_key(s) for s in specs}) == 1    # both read getGlobalSettings

    results = webstatus._read_group("Зал1", specs)
    assert len(world["reads"]) == 1                                 # one call, not two
    assert world["reads"][0][:3] == ("Зал1", "POST", "/getGlobalSettings")
    assert results[("Зал1", "Яркость")] == [("10.0.0.1:8080", True, 1200),
                                            ("10.0.0.2:8080", True, 1200)]
    assert results[("Зал1", "Гамма")] == [("10.0.0.1:8080", True, 2.2),
                                          ("10.0.0.2:8080", True, 2.2)]


def test_group_without_controllers_is_reported(world, monkeypatch):
    """A group with no addresses sends nothing (aoto.probe_raw returns early)."""
    monkeypatch.setattr(aoto, "_groups", {"Пусто": []})
    webstatus.refresh()
    param = _params(webstatus.snapshot(), "Пусто")["Яркость"]
    assert param["value"] == "нет контроллеров" and param["state"] == "error"
    assert param["controllers"] == []


# --- snapshot: Aoto ---------------------------------------------------------
def test_refresh_reads_every_group_once_and_pulls_pixelhue(world):
    webstatus.refresh()
    assert [r[0] for r in world["reads"]] == ["Зал1", "Зал2"]        # one read per group
    assert world["pulls"] == [1]                                    # device re-read once


def test_a_failing_pixelhue_pull_does_not_lose_the_aoto_data(world, monkeypatch):
    def boom():
        raise RuntimeError("device explodes")

    monkeypatch.setattr(pixelhue, "refresh_now", boom)
    webstatus.refresh()
    snap = webstatus.snapshot()
    assert _params(snap, "Зал1")["Яркость"]["value"] == "1200"       # Aoto section survives
    assert snap["age"] is not None


def test_aoto_values_aggregate_like_the_deck(world):
    webstatus.refresh()
    snap = webstatus.snapshot()
    bright = _params(snap, "Зал1")["Яркость"]
    assert bright["value"] == "1200" and bright["state"] == "ok"
    assert bright["percent"] == "80%"                               # 1200 of the @max 1500
    assert _params(snap, "Зал1")["Гамма"]["value"] == "2.2"
    assert _params(snap, "Зал2")["Яркость"]["percent"] == "20%"     # of the default ceiling


def test_disagreeing_controllers_are_mixed_with_a_breakdown(world):
    world["replies"][("Зал1", "/getGlobalSettings")]["10.0.0.2:8080"] = {
        "obj": {"brightness": 800, "gammaCoefficient": 2.2}}
    webstatus.refresh()
    bright = _params(webstatus.snapshot(), "Зал1")["Яркость"]
    assert bright["state"] == "mixed" and bright["value"] == "800-1200"
    assert bright["percent"] == "53-80%"
    assert [(c["addr"], c["value"]) for c in bright["controllers"]] == [
        ("10.0.0.1:8080", 1200), ("10.0.0.2:8080", 800)]


def test_unreachable_controller_shows_partial_then_error(world, monkeypatch):
    monkeypatch.setattr(aoto, "_groups", {"Зал1": ["10.0.0.1:8080", "10.0.0.2:8080", "10.0.0.4:8080"]})
    webstatus.refresh()
    bright = _params(webstatus.snapshot(), "Зал1")["Яркость"]
    assert bright["state"] == "partial" and bright["value"] == "1200 (2/3)"
    assert [c["ok"] for c in bright["controllers"]] == [True, True, False]

    world["replies"][("Зал1", "/getGlobalSettings")] = {}            # everyone down
    webstatus.refresh()
    bright = _params(webstatus.snapshot(), "Зал1")["Яркость"]
    assert bright["state"] == "error" and bright["value"] == "ERR"
    assert "percent" not in bright                                   # no value -> no %


def test_labels_map_hdr_values_and_reach_the_page(world, monkeypatch):
    monkeypatch.setattr(aoto, "_commands", [
        {"label": "HDR", "method": "POST", "path": "/getGlobalSettings", "body": {},
         "response_field": "obj.hdrSetting", "labels": {"2": "HLG"}},
    ])
    world["replies"][("Зал1", "/getGlobalSettings")]["10.0.0.1:8080"] = {"obj": {"hdrSetting": 2}}
    world["replies"][("Зал1", "/getGlobalSettings")]["10.0.0.2:8080"] = {"obj": {"hdrSetting": 3}}
    webstatus.refresh()
    hdr = _params(webstatus.snapshot(), "Зал1")["HDR"]
    assert hdr["value"] == "HLG/3"                                   # 3 has no label -> raw
    assert [c["value"] for c in hdr["controllers"]] == ["HLG", 3]


# --- snapshot: PC and PixelHue ---------------------------------------------
def test_pc_section_lists_hosts_with_alias_and_ping(world, monkeypatch):
    monkeypatch.setattr(pcbrowser, "_ping_at", time.monotonic() - 3.0)
    webstatus.refresh()
    pc = webstatus.snapshot()["pc"]
    assert pc["active_list"] == "Зал"
    assert 3.0 <= pc["checked_ago"] <= 3.5
    # pcbrowser.members() sorts aliased hosts first
    assert pc["hosts"] == [{"host": "10.0.0.5", "alias": "Режиссёрская", "up": False},
                           {"host": "10.0.0.9", "alias": None, "up": True}]


def test_pc_section_without_a_sweep_yet(world, monkeypatch):
    monkeypatch.setattr(pcbrowser, "_ping", {})
    webstatus.refresh()
    pc = webstatus.snapshot()["pc"]
    assert pc["checked_ago"] is None
    assert [h["up"] for h in pc["hosts"]] == [None, None]             # never pinged


def test_pixelhue_section_reports_node_flags_screens_and_presets(world, monkeypatch):
    monkeypatch.setattr(pixelhue, "PIXELHUE_HOST", "10.9.9.9")
    webstatus.refresh()
    ph = webstatus.snapshot()["pixelhue"]
    assert ph["host"] == "10.9.9.9:8088"            # the address comes from pixelhue itself
    assert ph["online"] == 1 and ph["version"] == "Q8 V1.0" and ph["error"] is None
    assert ph["mapping"] == 1 and ph["presets"] == 1
    assert ph["screens"] == [{"id": 6, "name": "Экран 1", "freeze": 0, "ftb": 1},
                             {"id": 7, "name": "Экран 2", "freeze": 0, "ftb": 0}]


def test_pixelhue_section_when_the_device_is_down(world, monkeypatch):
    monkeypatch.setattr(pixelhue, "_node", None)
    monkeypatch.setattr(pixelhue, "_last_err", "недоступен")
    monkeypatch.setattr(pixelhue, "_mapping", None)
    webstatus.refresh()
    ph = webstatus.snapshot()["pixelhue"]
    assert ph["online"] is None and ph["error"] == "недоступен" and ph["mapping"] is None


# --- freshness --------------------------------------------------------------
def test_a_reply_without_the_field_says_so_in_the_log(world):
    """The device answered, but the parameter is not in the reply -- that is a
    different problem from 'unreachable', and the log window must say which."""
    table = world["replies"][("Зал2", "/getGlobalSettings")]
    table["10.0.0.3:8080"] = {"obj": {"brightness": 300}}      # no gammaCoefficient
    webstatus.refresh()
    entries = [(e["source"], e["target"], e["message"]) for e in diag.entries()]
    assert entries == [("aoto", "Зал2/Гамма",
                        "в ответе нет поля obj.gammaCoefficient (в ответе: obj)")]

    table["10.0.0.3:8080"] = {"obj": {"brightness": 300, "gammaCoefficient": 2.4}}
    webstatus.refresh()
    assert diag.entries() == []                                # fixed -> row disappears


def test_snapshot_carries_the_problem_count(world):
    """The header badge counts what core/diag currently has open."""
    webstatus.refresh()
    assert webstatus.snapshot()["problems"] == 0
    diag.record("aoto", "http://10.0.0.1:8080/x", "timed out")
    assert webstatus.snapshot()["problems"] == 1


def test_log_entries_are_the_open_problems(world):
    diag.record("aoto", "http://10.0.0.1:8080/x", "timed out")
    assert webstatus.log_entries() == diag.entries()
    assert webstatus.log_entries()[0]["target"] == "http://10.0.0.1:8080/x"


def test_snapshot_is_instant_and_reports_age_and_a_viewer(world):
    assert webstatus.watched() is False
    empty = webstatus.snapshot()                                     # before any read
    assert empty["age"] is None and empty["stale"] is True
    assert webstatus.watched() is True                               # asking counts as watching

    webstatus.refresh()
    snap = webstatus.snapshot()
    assert 0 <= snap["age"] < 1 and snap["stale"] is False
    assert snap["interval"] == WEB_REFRESH_INTERVAL
    assert snap["read_at"]                                          # wall clock of the read


def test_idle_page_stops_counting_as_a_viewer(world, monkeypatch):
    webstatus.snapshot()
    assert webstatus.watched() is True
    monkeypatch.setattr(webstatus, "_viewer_until", time.monotonic() - 1)
    assert webstatus.watched() is False                              # tab closed -> reads stop


def test_a_page_landing_on_stale_data_wakes_the_refresher(world, monkeypatch):
    webstatus.refresh()
    webstatus.snapshot()
    assert webstatus._wake.is_set() is False                         # fresh: no early wake
    monkeypatch.setattr(webstatus, "_read_at", time.monotonic() - 30)
    webstatus.snapshot()
    assert webstatus._wake.is_set() is True                          # stale: read now


def test_start_spawns_one_daemon_thread(world, monkeypatch):
    started: list = []

    class FakeThread:
        def __init__(self, target=None, name=None, daemon=None):
            started.append((target, name, daemon))

        def start(self):
            pass

    monkeypatch.setattr(webstatus.threading, "Thread", FakeThread)
    webstatus.start()
    assert len(started) == 1 and started[0][1] == "webstatus" and started[0][2] is True


# --- the page --------------------------------------------------------------
def test_page_html_falls_back_when_the_file_is_missing(world, monkeypatch):
    monkeypatch.setattr(webstatus, "WEB_PAGE", WEB_PAGE.parent / "nope.html")
    page = webstatus.page_html()
    assert "<html" in page and "/status" in page and "nope.html" in page


def test_shipped_page_polls_the_status_endpoint():
    """The bundled page must talk to /status (and to nothing external)."""
    page = WEB_PAGE.read_text(encoding="utf-8")
    assert 'fetch("/status"' in page
    assert "http://" not in page and "https://" not in page


def test_page_url_points_at_this_server():
    """The URL the Develop tab opens in a browser on this machine."""
    from core.config import PORT

    assert webstatus.page_url() == f"http://127.0.0.1:{PORT}/"
