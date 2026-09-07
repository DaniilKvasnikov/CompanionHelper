"""PixelHue Q8 LED-processor control over HTTP, as a dynamic main-menu tab.

A "PixelHue" button on the main menu opens a per-device control page for a
PixelHue Q8 (also P10/P20/P80) node. One device: host/port/nodeId live in
core/config.py (`PIXELHUE_*`, override per machine in config.local.json).

Auth is a JWT: HS256, payload {SN}, secret = `startTime` from the public
`node/open-detail` call -- no password, rebuilt automatically after a device
reboot (a stale token answers HTTP 401). Everything else goes through the
`/unico/v1` namespace, a superset of `/pixelhue/v1` (the documented prefix
404s on `layers/window` / `layers/zorder`). See PIXELHUE_API_GUIDE.md.

Inside the tab:
  - a status button (node version + online/offline, re-polls on press);
  - global FTB / Freeze toggles acting on every usable screen at once;
  - a per-screen submenu (real outputs only -- MVR screens are dropped) with
    Take / Cut / Freeze / FTB;
  - a preset list (apply to the program region).

Screens and presets are read from the device and cached here; a background
poller (start) keeps them fresh and redraws pages so toggles light up truly.
Providers only read caches; HTTP happens on press or in the poller.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import (
    COLORS,
    PIXELHUE_FTB_TIME_MS,
    PIXELHUE_HOST,
    PIXELHUE_NODE_ID,
    PIXELHUE_POLL_INTERVAL,
    PIXELHUE_PORT,
    PIXELHUE_PRESET_TARGET_REGION,
    PIXELHUE_SKIP_SCREEN_TYPES,
    PIXELHUE_TAKE_TIME_MS,
    PIXELHUE_TIMEOUT,
)
from .constants import After, Kind
from .model import ActionNode, MenuNode

log = logging.getLogger("pixelhue")

_SCREENS = "/unico/v1/screen/list-detail"
_NODE_DETAIL = "/pixelhue/v1/node/detail?nodeId={node}"
_OPEN_DETAIL = "/pixelhue/v1/node/open-detail?nodeId={node}"


@dataclass
class Screen:
    screen_id: int
    guid: str
    name: str
    freeze: int = 0      # 0|1
    ftb_enable: int = 0  # 0|1


@dataclass
class Preset:
    guid: str
    name: str
    serial: int = 0


_lock = threading.RLock()
_token: str | None = None            # JWT cache (in memory only; see API guide §9.8)
_node: dict | None = None            # node/detail data (version, online, ...)
_last_err: str | None = None         # why the last poll failed (for the status button)
_screens: list[Screen] = []          # usable (non-MVR) screens, cached
_presets: list[Preset] = []          # presets, cached


# --- JWT (see API guide §3.1) ---------------------------------------------
def _b64url(b: bytes) -> bytes:
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def build_token(sn: str, start_time: str) -> str:
    """HS256 JWT with payload {SN}, secret = startTime; no exp/iat (token never dies)."""
    seg = _b64url(b'{"alg":"HS256","typ":"JWT"}') + b"." + \
        _b64url(json.dumps({"SN": sn}, separators=(",", ":")).encode())
    sig = hmac.new(start_time.encode(), seg, hashlib.sha256).digest()
    return (seg + b"." + _b64url(sig)).decode()


def _make_token() -> str | None:
    """Read node/open-detail (public) and build the JWT; None if unreachable."""
    url = f"http://{PIXELHUE_HOST}:{PIXELHUE_PORT}" + _OPEN_DETAIL.format(node=PIXELHUE_NODE_ID)
    try:
        with urllib.request.urlopen(url, timeout=PIXELHUE_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001 - device down must not crash the deck
        log.warning("pixelhue open-detail failed: %s", e)
        return None
    data = payload.get("data") or {}
    sn, start = data.get("sn"), data.get("startTime")
    if not sn or start is None:
        log.warning("pixelhue open-detail missing sn/startTime: %s", payload)
        return None
    return build_token(sn, str(start))


def _get_token() -> str | None:
    global _token
    with _lock:
        if _token is not None:
            return _token
    token = _make_token()
    if token is not None:
        with _lock:
            _token = token
    return token


# --- HTTP (all fail-soft) ---------------------------------------------------
def _request(method: str, path: str, body=None, retried: bool = False) -> tuple[bool, object]:
    """One authed JSON request. (True, data) on device code 0/200, else (False, text).

    A 401 means the device rebooted (startTime changed) -- drop the cached
    token, rebuild it once and retry.
    """
    global _token
    token = _get_token()
    if not token:
        return False, "нет токена (device недоступен?)"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"http://{PIXELHUE_HOST}:{PIXELHUE_PORT}{path}", data=data, method=method.upper(),
        headers={"Authorization": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=PIXELHUE_TIMEOUT) as resp:
            text = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 401 and not retried:
            with _lock:
                _token = None
            log.info("pixelhue token stale (401), rebuilding and retrying")
            return _request(method, path, body, retried=True)
        return False, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return False, str(e).strip()[:60]
    try:
        payload = json.loads(text)
    except Exception:  # noqa: BLE001
        return False, "не JSON"
    code = payload.get("code")
    if code in (0, 200):
        return True, payload.get("data")
    return False, str(payload.get("message") or f"code {code}")[:60]


# --- parsing (pure) ---------------------------------------------------------
def parse_screens(raw) -> list[Screen]:
    """Drop invalid and MVR (screenIdObj.type in PIXELHUE_SKIP_SCREEN_TYPES) screens."""
    out: list[Screen] = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict):
            continue
        sidobj = r.get("screenIdObj") or {}
        if sidobj.get("type") in PIXELHUE_SKIP_SCREEN_TYPES:
            continue
        general = r.get("general") or {}
        guid, name = r.get("guid"), general.get("name")
        if not (isinstance(guid, str) and guid and isinstance(name, str) and name):
            continue
        ftb = r.get("ftb") or {}
        try:
            out.append(Screen(
                int(r["screenId"]), guid, name,
                int(r.get("freeze") or 0), int(ftb.get("enable") or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def parse_presets(raw) -> list[Preset]:
    out: list[Preset] = []
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict):
            continue
        guid, name = p.get("guid"), p.get("name")
        if not (isinstance(guid, str) and guid and isinstance(name, str) and name):
            continue
        try:
            serial = int(p.get("serial", 0))
        except (TypeError, ValueError):
            serial = 0
        out.append(Preset(guid, name, serial))
    return out


# --- cached state -----------------------------------------------------------
def screens() -> list[Screen]:
    with _lock:
        return list(_screens)


def presets() -> list[Preset]:
    with _lock:
        return list(_presets)


def _screen_by_id(screen_id: int) -> Screen | None:
    return next((s for s in screens() if s.screen_id == screen_id), None)


def _flag_state(attr: str) -> int | None:
    """Aggregate a 0/1 flag over usable screens: 1 all on, 0 all off, None mixed."""
    vals = {getattr(s, attr) for s in screens()}
    if len(vals) == 1:
        return next(iter(vals))
    return None


def _flag_word(v: int | None) -> str:
    return "on" if v == 1 else ("off" if v == 0 else "mix")


def _green():
    return COLORS[Kind.FEEDBACK]


def _red():
    return COLORS[Kind.BACK]


# --- polling ----------------------------------------------------------------
def _pull_node() -> None:
    """Refresh the node info. A failed fetch means offline -> clear the cache."""
    global _node, _last_err
    ok, data = _request("GET", _NODE_DETAIL.format(node=PIXELHUE_NODE_ID))
    with _lock:
        _node = data if ok and isinstance(data, dict) else None
        _last_err = None if ok else (str(data) if data else "недоступен")


def _pull_screens() -> None:
    global _screens
    ok, data = _request("GET", _SCREENS)
    if ok and isinstance(data, dict):            # keep the last good list on failure
        parsed = parse_screens(data.get("list"))
        with _lock:
            _screens = parsed


def _pull_presets() -> None:
    global _presets
    ok, data = _request("GET", "/unico/v1/preset")
    if ok and isinstance(data, dict):
        parsed = parse_presets(data.get("list"))
        with _lock:
            _presets = parsed


def _pull_all() -> None:
    _pull_node()
    _pull_screens()
    _pull_presets()


def start(on_update) -> None:
    """Background poller for node/screens/presets. `on_update` redraws the deck."""

    def loop():
        while True:
            try:
                _pull_all()
            except Exception as e:  # noqa: BLE001 - never let the poller die
                log.warning("pixelhue poll failed: %s", e)
            try:
                on_update()
            except Exception as e:  # noqa: BLE001
                log.warning("pixelhue on_update failed: %s", e)
            time.sleep(PIXELHUE_POLL_INTERVAL)

    threading.Thread(target=loop, name="pixelhue-poller", daemon=True).start()


# --- actions (called from on_press; run outside state.lock) ------------------
def _apply(method: str, path: str, body) -> str:
    ok, res = _request(method, path, body)
    return "OK" if ok else f"ERR {res}"


def _state_line(sid: int, attr: str) -> str:
    s = _screen_by_id(sid)
    return _flag_word(getattr(s, attr) if s else None)


# body builders (pure, tested) -----------------------------------------------
def take_body(s: Screen) -> dict:
    return {
        "direction": 0, "effectSelect": 1, "screenGuid": s.guid,
        "screenId": s.screen_id, "screenName": s.name, "swapEnable": 1,
        "switchEffect": {"type": 1, "time": PIXELHUE_TAKE_TIME_MS},
    }


def cut_body(s: Screen) -> dict:
    return {"direction": 0, "screenId": s.screen_id, "swapEnable": 1}


def freeze_body(screen_id: int, freeze: int) -> dict:
    return {"screenId": screen_id, "freeze": freeze}


def ftb_body(screen_id: int, enable: int) -> dict:
    return {"screenId": screen_id, "ftb": {"enable": enable, "time": PIXELHUE_FTB_TIME_MS}}


def preset_body(p: Preset) -> dict:
    return {
        "serial": p.serial, "presetId": p.guid,
        "targetRegion": PIXELHUE_PRESET_TARGET_REGION,
        "auxiliary": {
            "keyFrame": {"enable": 1},
            "switchEffect": {"type": 1, "time": PIXELHUE_TAKE_TIME_MS},
            "swapEnable": 1,
            "effect": {"enable": 1},
        },
    }


# press handlers ---------------------------------------------------------------
def _take(sid: int) -> str:
    s = _screen_by_id(sid)
    return _apply("PUT", "/unico/v1/screen/take", [take_body(s)]) if s else "ERR нет экрана"


def _cut(sid: int) -> str:
    s = _screen_by_id(sid)
    return _apply("PUT", "/unico/v1/screen/cut", [cut_body(s)]) if s else "ERR нет экрана"


def _toggle_freeze(sid: int) -> str:
    s = _screen_by_id(sid)
    if not s:
        return ""
    _apply("PUT", "/unico/v1/screen/freeze", [freeze_body(sid, 0 if s.freeze else 1)])
    _pull_screens()
    return ""


def _toggle_ftb(sid: int) -> str:
    s = _screen_by_id(sid)
    if not s:
        return ""
    _apply("PUT", "/unico/v1/screen/ftb", [ftb_body(sid, 0 if s.ftb_enable else 1)])
    _pull_screens()
    return ""


def _toggle_global_freeze() -> str:
    ss = screens()
    if not ss:
        return ""
    target = 0 if _flag_state("freeze") == 1 else 1  # all on -> off; off/mixed -> on
    _apply("PUT", "/unico/v1/screen/freeze",
           [freeze_body(s.screen_id, target) for s in ss])
    _pull_screens()
    return ""


def _toggle_global_ftb() -> str:
    ss = screens()
    if not ss:
        return ""
    target = 0 if _flag_state("ftb_enable") == 1 else 1  # all on -> off; off/mixed -> on
    _apply("PUT", "/unico/v1/screen/ftb",
           [ftb_body(s.screen_id, target) for s in ss])
    _pull_screens()
    return ""


def _apply_preset(guid: str) -> str:
    p = next((p for p in presets() if p.guid == guid), None)
    return _apply("POST", "/unico/v1/preset/apply", preset_body(p)) if p else "ERR нет пресета"


def _refresh_now() -> str:
    _pull_all()
    return ""


# --- menu tree (providers) ---------------------------------------------------
def attach(root: MenuNode) -> None:
    """Insert the PixelHue menu after the ПК/PDQ/AOTO/Touch/OSC tabs."""
    idx = 0
    for i, child in enumerate(root.children):
        if getattr(child, "name", "") in ("__pc__", "__pdq__", "__aoto__", "__touch__", "__osc__"):
            idx = i + 1
    root.children.insert(
        idx, MenuNode(name="__pixelhue__", path=None, label="PixelHue", provider=_tab_children)
    )


def _tab_children(node) -> list:
    if not PIXELHUE_HOST:
        return [ActionNode(name="none", label="PixelHue\nнет адреса",
                           kind=Kind.COMMAND, after=After.TEXT, on_press=lambda: "")]
    status_text, status_color = _status()
    out: list = [
        ActionNode(name="status", label=status_text, kind=Kind.COMMAND,
                   after=After.RERENDER, color_fn=status_color, on_press=_refresh_now),
        ActionNode(name="ftb", label=f"FTB\n{_flag_word(_flag_state('ftb_enable'))}",
                   kind=Kind.COMMAND, after=After.RERENDER,
                   color_fn=_global_color("ftb_enable"), on_press=_toggle_global_ftb),
        ActionNode(name="freeze", label=f"Freeze\n{_flag_word(_flag_state('freeze'))}",
                   kind=Kind.COMMAND, after=After.RERENDER,
                   color_fn=_global_color("freeze"), on_press=_toggle_global_freeze),
    ]
    if screens():
        out.append(MenuNode(name="__screens__", path=None, label="Экраны",
                            provider=_screens_menu))
    if presets():
        out.append(MenuNode(name="__presets__", path=None, label="Пресеты",
                            provider=_presets_menu))
    return out


def _status() -> tuple[str, object]:
    """(status-button text, color_fn) from the node cache."""
    with _lock:
        node, err = _node, _last_err
    if node is None:
        return ("PixelHue\n" + (err or "…"), lambda: _red())
    online = node.get("online")
    version = node.get("version") or "PixelHue"
    if online in (1, "1", True):
        return (f"{version}\nonline", lambda: _green())
    return (f"{version}\noffline", lambda: _red())


def _global_color(attr: str):
    def color():
        return _green() if _flag_state(attr) == 1 else None
    return color


def _screen_color(sid: int, attr: str):
    def color():
        s = _screen_by_id(sid)
        return _green() if s and getattr(s, attr) == 1 else None
    return color


def _screens_menu(node) -> list:
    return [
        MenuNode(name=str(s.screen_id), path=None, label=s.name,
                 provider=_screen_buttons, context={"sid": s.screen_id})
        for s in screens()
    ]


def _screen_buttons(node) -> list:
    sid = node.context["sid"]
    s = _screen_by_id(sid)
    if s is None:
        return []
    return [
        ActionNode(name="take", label="Take", kind=Kind.COMMAND, after=After.TEXT,
                   on_press=lambda sid=sid: _take(sid)),
        ActionNode(name="cut", label="Cut", kind=Kind.COMMAND, after=After.TEXT,
                   on_press=lambda sid=sid: _cut(sid)),
        ActionNode(name="freeze", label=f"Freeze\n{_state_line(sid, 'freeze')}",
                   kind=Kind.COMMAND, after=After.RERENDER,
                   color_fn=_screen_color(sid, "freeze"),
                   on_press=lambda sid=sid: _toggle_freeze(sid)),
        ActionNode(name="ftb", label=f"FTB\n{_state_line(sid, 'ftb_enable')}",
                   kind=Kind.COMMAND, after=After.RERENDER,
                   color_fn=_screen_color(sid, "ftb_enable"),
                   on_press=lambda sid=sid: _toggle_ftb(sid)),
    ]


def _presets_menu(node) -> list:
    return [
        ActionNode(name=p.guid, label=p.name, kind=Kind.COMMAND, after=After.TEXT,
                   on_press=lambda guid=p.guid: _apply_preset(guid))
        for p in presets()
    ]
