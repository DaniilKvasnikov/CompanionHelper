"""pixelhue: JWT, parsing, HTTP edge handling, actions, and the menu tree.

Real HTTP is faked: urllib.request.urlopen is monkeypatched for the request
tests, pixelhue._request for the poll/action tests, and module caches are set
directly for the menu-tree tests. No live PixelHue device is touched.
"""
import base64
import hashlib
import hmac
import io
import json
import urllib.error

import pytest

from core import pixelhue
from core.config import COLORS
from core.constants import After, Kind
from core.model import ActionNode, MenuNode


class _Resp:
    def __init__(self, text):
        self._b = text.encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def state(monkeypatch):
    """Empty caches only; no disk or network. Token/request seams are per-test."""
    monkeypatch.setattr(pixelhue, "_token", None)
    monkeypatch.setattr(pixelhue, "_node", None)
    monkeypatch.setattr(pixelhue, "_last_err", None)
    monkeypatch.setattr(pixelhue, "_mapping", None)
    monkeypatch.setattr(pixelhue, "_screens", [])
    monkeypatch.setattr(pixelhue, "_presets", [])
    return pixelhue


def _raw_screen(sid, name, type_=2, freeze=0, ftb=0, guid=None):
    return {
        "screenId": sid, "screenIdObj": {"id": sid, "type": type_},
        "general": {"name": name}, "guid": guid or f"g{sid}",
        "select": 0, "freeze": freeze, "enable": 1,
        "ftb": {"enable": ftb, "time": 700},
    }


def _screen(sid, name, freeze=0, ftb=0):
    return pixelhue.Screen(sid, f"g{sid}", name, freeze, ftb)


# --- JWT ------------------------------------------------------------------
def _dec(s):
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


def test_build_token_structure_and_signature():
    tok = pixelhue.build_token("SN1", "1234567890")
    head, payload, sig = tok.split(".")
    assert json.loads(_dec(head)) == {"alg": "HS256", "typ": "JWT"}
    assert json.loads(_dec(payload)) == {"SN": "SN1"}     # no exp/iat claims
    expect = base64.urlsafe_b64encode(
        hmac.new(b"1234567890", f"{head}.{payload}".encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    assert sig == expect


def test_make_token_builds_and_get_token_caches(state, monkeypatch):
    seen = []

    def fake_urlopen(*a, **k):
        seen.append(1)
        return _Resp(json.dumps({"code": 0, "data": {
            "sn": "SN1", "startTime": "1234567890"}}))

    monkeypatch.setattr(pixelhue.urllib.request, "urlopen", fake_urlopen)
    assert pixelhue._get_token() == pixelhue.build_token("SN1", "1234567890")
    assert pixelhue._get_token() == pixelhue.build_token("SN1", "1234567890")
    assert len(seen) == 1                                   # cached after the first build


def test_make_token_fails_soft(state, monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(pixelhue.urllib.request, "urlopen", boom)
    assert pixelhue._make_token() is None


# --- parsing --------------------------------------------------------------
def test_parse_screens_drops_mvr_and_invalid():
    raw = [
        _raw_screen(6, "Screen 1", freeze=1, ftb=1),
        _raw_screen(1, "MVR 1", type_=8),                       # MVR -> dropped
        {"screenId": 2, "general": {"name": "No Guid"}},        # blank guid -> dropped
        {"screenId": 3, "screenIdObj": {}, "guid": "g3", "general": {"name": ""}},  # blank name
        "junk",
    ]
    out = pixelhue.parse_screens(raw)
    assert [(s.screen_id, s.name, s.freeze, s.ftb_enable) for s in out] == [(6, "Screen 1", 1, 1)]


def test_parse_screens_tolerates_missing_ftb_freeze():
    raw = [{"screenId": 6, "screenIdObj": {"type": 2}, "guid": "g", "general": {"name": "A"}}]
    out = pixelhue.parse_screens(raw)
    assert out == [pixelhue.Screen(6, "g", "A", 0, 0)]


def test_parse_presets_keeps_valid_and_parses_serial():
    raw = [
        {"guid": "p1", "name": "Preset A", "serial": "3"},
        {"guid": "p2", "name": "Preset B"},
        {"guid": "", "name": "Empty"},                          # dropped
        "junk",
    ]
    out = pixelhue.parse_presets(raw)
    assert [(p.guid, p.name, p.serial) for p in out] == [("p1", "Preset A", 3), ("p2", "Preset B", 0)]


# --- request bodies ---------------------------------------------------------
def test_take_body():
    s = _screen(6, "Screen 1")
    body = pixelhue.take_body(s)
    assert body["screenId"] == 6 and body["screenGuid"] == "g6" and body["screenName"] == "Screen 1"
    assert body["switchEffect"] == {"type": 1, "time": pixelhue.PIXELHUE_TAKE_TIME_MS}
    assert body["direction"] == 0 and body["effectSelect"] == 1 and body["swapEnable"] == 1


def test_cut_freeze_ftb_bodies():
    assert pixelhue.cut_body(_screen(6, "S")) == {"direction": 0, "screenId": 6, "swapEnable": 1}
    assert pixelhue.freeze_body(6, 1) == {"screenId": 6, "freeze": 1}
    assert pixelhue.ftb_body(6, 0) == {"screenId": 6, "ftb": {"enable": 0, "time": pixelhue.PIXELHUE_FTB_TIME_MS}}


def test_mapping_body():
    assert pixelhue.mapping_body(1, 1) == {"nodeId": 1, "enable": 1}
    assert pixelhue.mapping_body(1, 0) == {"nodeId": 1, "enable": 0}


def test_preset_body_matches_companion_shape():
    body = pixelhue.preset_body(pixelhue.Preset("p1", "Preset A", 3))
    assert body == {
        "serial": 3, "presetId": "p1", "targetRegion": pixelhue.PIXELHUE_PRESET_TARGET_REGION,
        "auxiliary": {
            "keyFrame": {"enable": 1},
            "switchEffect": {"type": 1, "time": pixelhue.PIXELHUE_TAKE_TIME_MS},
            "swapEnable": 1,
            "effect": {"enable": 1},
        },
    }


# --- HTTP edge handling ------------------------------------------------------
def test_request_no_token(state, monkeypatch):
    monkeypatch.setattr(pixelhue, "_get_token", lambda: None)
    calls = []
    monkeypatch.setattr(pixelhue.urllib.request, "urlopen",
                        lambda *a, **k: calls.append(1))
    ok, res = pixelhue._request("GET", "/x")
    assert ok is False and calls == []


def test_request_ok_and_code_error(state, monkeypatch):
    monkeypatch.setattr(pixelhue, "_get_token", lambda: "t")
    payloads = iter([
        '{"code": 0, "data": {"list": [1]}}',
        '{"code": 200, "data": {}}',
        '{"code": 8210, "message": "manage param invalid"}',
        'not json at all',
    ])
    monkeypatch.setattr(pixelhue.urllib.request, "urlopen",
                        lambda *a, **k: _Resp(next(payloads)))
    assert pixelhue._request("PUT", "/a", {}) == (True, {"list": [1]})
    assert pixelhue._request("PUT", "/a", {}) == (True, {})
    ok, res = pixelhue._request("PUT", "/a", {})
    assert ok is False and "manage param invalid" in res
    ok, res = pixelhue._request("PUT", "/a", {})
    assert ok is False and res == "не JSON"


def test_request_network_error_is_soft(state, monkeypatch):
    monkeypatch.setattr(pixelhue, "_get_token", lambda: "t")

    def boom(*a, **k):
        raise OSError("timed out")
    monkeypatch.setattr(pixelhue.urllib.request, "urlopen", boom)
    ok, res = pixelhue._request("GET", "/a")
    assert ok is False and res


def test_request_401_clears_token_and_retries_once(state, monkeypatch):
    monkeypatch.setattr(pixelhue, "_token", "stale")
    monkeypatch.setattr(pixelhue, "_get_token", lambda: "stale")
    calls = []

    def fake_urlopen(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError("http://x/", 401, "Unauthorized", {}, io.BytesIO(b""))
        return _Resp('{"code": 0, "data": {}}')

    monkeypatch.setattr(pixelhue.urllib.request, "urlopen", fake_urlopen)
    assert pixelhue._request("GET", "/a") == (True, {})
    assert calls == [1, 1]
    assert pixelhue._token is None          # invalidated before the retry


def test_request_non_401_http_error(state, monkeypatch):
    monkeypatch.setattr(pixelhue, "_get_token", lambda: "t")

    def fake_urlopen(*a, **k):
        raise urllib.error.HTTPError("http://x/", 404, "Cannot PUT", {}, io.BytesIO(b""))
    monkeypatch.setattr(pixelhue.urllib.request, "urlopen", fake_urlopen)
    ok, res = pixelhue._request("PUT", "/x")
    assert ok is False and "404" in res


# --- polling ---------------------------------------------------------------
def test_pull_all_populates_caches(state, monkeypatch):
    def fake(method, path, body=None, retried=False):
        if "node/detail" in path:
            return True, {"online": 1, "version": "V2.0.0"}
        if path == pixelhue._SCREENS:
            return True, {"list": [_raw_screen(6, "Screen 1", freeze=1, ftb=1),
                                   _raw_screen(1, "MVR 1", type_=8)]}
        if path == "/unico/v1/preset":
            return True, {"list": [{"guid": "p1", "name": "Preset A", "serial": "3"}]}
        if pixelhue._LOCATION in path:
            return True, {"nodeId": 1, "enable": 1}
        return False, "unexpected"

    monkeypatch.setattr(pixelhue, "_request", fake)
    pixelhue._pull_all()
    assert [s.screen_id for s in pixelhue.screens()] == [6]
    assert [(p.guid, p.serial) for p in pixelhue.presets()] == [("p1", 3)]
    assert pixelhue._node == {"online": 1, "version": "V2.0.0"}
    assert pixelhue.mapping_enabled() == 1


def test_pull_failure_keeps_screens_but_marks_node_offline(state, monkeypatch):
    monkeypatch.setattr(pixelhue, "_screens", [_screen(6, "Screen 1")])
    monkeypatch.setattr(pixelhue, "_presets", [pixelhue.Preset("p1", "Preset A", 0)])

    def fake(method, path, body=None, retried=False):
        return False, "недоступен"

    monkeypatch.setattr(pixelhue, "_request", fake)
    pixelhue._pull_all()
    assert len(pixelhue.screens()) == 1          # last good list survives
    assert len(pixelhue.presets()) == 1
    assert pixelhue._node is None                # but the node shows offline
    assert pixelhue._last_err == "недоступен"


# --- actions ----------------------------------------------------------------
def test_take_sends_full_body_and_summary(state, monkeypatch):
    monkeypatch.setattr(pixelhue, "_screens", [_screen(6, "Screen 1")])
    seen = {}
    monkeypatch.setattr(pixelhue, "_request",
                        lambda m, p, b=None, retried=False: seen.update(m=m, p=p, b=b) or (True, {}))
    assert pixelhue._take(6) == "OK"
    assert seen["m"] == "PUT" and seen["p"] == "/unico/v1/screen/take"
    assert seen["b"] == [pixelhue.take_body(_screen(6, "Screen 1"))]


def test_toggle_freezes_then_repolls(state, monkeypatch):
    monkeypatch.setattr(pixelhue, "_screens", [_screen(6, "Screen 1", freeze=1)])
    seen, repoll = [], []
    monkeypatch.setattr(pixelhue, "_request",
                        lambda m, p, b=None, retried=False: seen.append((p, b)) or (True, {}))
    monkeypatch.setattr(pixelhue, "_pull_screens", lambda: repoll.append(1))
    assert pixelhue._toggle_freeze(6) == ""
    assert seen == [("/unico/v1/screen/freeze", [{"screenId": 6, "freeze": 0}])]
    assert repoll == [1]


def test_global_toggle_all_on_goes_off_mixed_goes_on(state, monkeypatch):
    monkeypatch.setattr(pixelhue, "_screens", [_screen(1, "A", freeze=1), _screen(2, "B", freeze=1)])
    seen = []
    monkeypatch.setattr(pixelhue, "_request",
                        lambda m, p, b=None, retried=False: seen.append(b) or (True, {}))
    monkeypatch.setattr(pixelhue, "_pull_screens", lambda: None)
    pixelhue._toggle_global_freeze()
    assert seen == [[{"screenId": 1, "freeze": 0}, {"screenId": 2, "freeze": 0}]]

    monkeypatch.setattr(pixelhue, "_screens", [_screen(1, "A", freeze=1), _screen(2, "B", freeze=0)])
    pixelhue._toggle_global_freeze()
    assert seen[-1] == [{"screenId": 1, "freeze": 1}, {"screenId": 2, "freeze": 1}]


def test_global_toggle_no_screens_is_noop(state, monkeypatch):
    called = []
    monkeypatch.setattr(pixelhue, "_request", lambda *a, **k: called.append(1) or (True, {}))
    assert pixelhue._toggle_global_ftb() == ""
    assert called == []


def test_mapping_toggle_posts_and_repolls(state, monkeypatch):
    monkeypatch.setattr(pixelhue, "_mapping", 1)
    seen, repoll = [], []
    monkeypatch.setattr(pixelhue, "_request",
                        lambda m, p, b=None, retried=False: seen.append((p, b)) or (True, {}))
    monkeypatch.setattr(pixelhue, "_pull_mapping", lambda: repoll.append(1))
    assert pixelhue._toggle_mapping() == ""
    assert seen == [(pixelhue._LOCATION,
                     {"nodeId": pixelhue.PIXELHUE_NODE_ID, "enable": 0})]
    assert repoll == [1]


def test_mapping_toggle_unknown_state_is_noop(state, monkeypatch):
    called = []
    monkeypatch.setattr(pixelhue, "_request", lambda *a, **k: called.append(1) or (True, {}))
    assert pixelhue._toggle_mapping() == ""
    assert called == []


# --- menu tree --------------------------------------------------------------
def test_attach_inserts_after_osc_tab():
    root = MenuNode("", None, "", children=[
        MenuNode("__pc__", None, "PC"), MenuNode("__osc__", None, "OSC"),
        MenuNode("x", None, "X"),
    ])
    pixelhue.attach(root)
    names = [c.name for c in root.children]
    assert names == ["__pc__", "__osc__", "__pixelhue__", "x"]
    assert root.children[2].label == "PixelHue"


def test_tab_children_no_host(state, monkeypatch):
    monkeypatch.setattr(pixelhue, "PIXELHUE_HOST", "")
    kids = pixelhue._tab_children(None)
    assert len(kids) == 1 and "нет адреса" in kids[0].label


def test_tab_children_screens_and_presets_submenus(state, monkeypatch):
    monkeypatch.setattr(pixelhue, "_node", {"online": 1, "version": "V2.0.0"})
    monkeypatch.setattr(pixelhue, "_mapping", 1)
    monkeypatch.setattr(pixelhue, "_screens", [_screen(6, "Screen 1")])
    monkeypatch.setattr(pixelhue, "_presets", [pixelhue.Preset("p1", "Preset A", 0)])
    kids = pixelhue._tab_children(None)
    by_name = {k.name: k for k in kids}
    assert by_name["status"].label == "V2.0.0\nonline"
    assert by_name["status"].color_fn() == COLORS[Kind.FEEDBACK]
    assert by_name["ftb"].after == After.RERENDER and "off" in by_name["ftb"].label
    assert by_name["mapping"].label == "Mapping\non"
    assert by_name["mapping"].after == After.RERENDER
    assert by_name["mapping"].color_fn() == COLORS[Kind.FEEDBACK]
    assert by_name["__screens__"].label == "Экраны"
    assert by_name["__presets__"].label == "Пресеты"


def test_tab_children_offline_state(state, monkeypatch):
    monkeypatch.setattr(pixelhue, "_node", {"online": 0, "version": "V2.0.0"})
    kids = pixelhue._tab_children(None)
    status = next(k for k in kids if k.name == "status")
    assert status.label == "V2.0.0\noffline"
    assert status.color_fn() == COLORS[Kind.BACK]


def test_screen_submenu_buttons(state, monkeypatch):
    monkeypatch.setattr(pixelhue, "_screens", [_screen(6, "Screen 1", freeze=1, ftb=0)])
    menus = pixelhue._screens_menu(None)
    assert len(menus) == 1 and menus[0].context == {"sid": 6}
    kids = {k.name: k for k in pixelhue._screen_buttons(menus[0])}
    assert kids["take"].after == After.TEXT and kids["cut"].after == After.TEXT
    assert kids["freeze"].after == After.RERENDER and kids["freeze"].label == "Freeze\non"
    assert kids["freeze"].color_fn() == COLORS[Kind.FEEDBACK]
    assert kids["ftb"].label == "FTB\noff"
    assert kids["ftb"].color_fn() is None

    seen = []
    monkeypatch.setattr(pixelhue, "_request",
                        lambda m, p, b=None, retried=False: seen.append((p, b)) or (True, {}))
    monkeypatch.setattr(pixelhue, "_pull_screens", lambda: None)
    assert kids["freeze"].on_press() == ""
    assert seen == [("/unico/v1/screen/freeze", [{"screenId": 6, "freeze": 0}])]


def test_preset_menu_press_applies(state, monkeypatch):
    monkeypatch.setattr(pixelhue, "_presets", [pixelhue.Preset("p1", "Preset A", 3)])
    kids = pixelhue._presets_menu(None)
    assert len(kids) == 1 and kids[0].label == "Preset A"
    seen = {}
    monkeypatch.setattr(pixelhue, "_request",
                        lambda m, p, b=None, retried=False: seen.update(m=m, p=p, b=b) or (True, {}))
    assert kids[0].on_press() == "OK"
    assert seen["m"] == "POST" and seen["p"] == "/unico/v1/preset/apply"
    assert seen["b"] == pixelhue.preset_body(pixelhue.Preset("p1", "Preset A", 3))
