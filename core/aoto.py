"""Aoto LED-processor control over HTTP, as a dynamic main-menu tab.

An "AOTO" button on the main menu opens a list of groups. Each group is a file
in aoto/groups/ listing controller addresses (one host:port per line). Selecting
a group opens its command menu; pressing a command sends an HTTP request to
EVERY controller in that group at once.

Commands are shared across groups and defined in aoto/commands.json, e.g.:

    {"label": "Блэкаут", "method": "POST",
     "path": "/ng_ctrl_sys/globalSettings/setScreenStatus", "body": {"type": 1}}

A command with a "response_field" is a *status* command: that field is read from
each controller's JSON reply, aggregated across the group, and shown on the
button — refreshed by a background poller and when pressed. Everything is
fail-soft: an unreachable controller becomes an error count, never a crash.

This module owns the group/command catalog + the status cache; providers only
read those caches (no I/O), and the HTTP work happens on press or in the poller
thread, never during a render. See CLAUDE.md for the conventions.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .config import (
    AOTO_BRIGHTNESS_LIMIT_DEFAULT,
    AOTO_BRIGHTNESS_LIMITS,
    AOTO_BRIGHTNESS_MAX_DIRECTIVE,
    AOTO_BRIGHTNESS_MIN,
    AOTO_BRIGHTNESS_PERCENT,
    AOTO_BRIGHTNESS_STATUS_LABEL,
    AOTO_BRIGHTNESS_STEP,
    AOTO_COMMANDS_FILE,
    AOTO_GROUPS_DIR,
    AOTO_HDR_MODES,
    AOTO_HDR_STATUS_LABEL,
    AOTO_HTTP_TIMEOUT,
    AOTO_POLL_INTERVAL,
    AOTO_SET_BRIGHTNESS_KEY,
    AOTO_SET_BRIGHTNESS_PATH,
    AOTO_SET_HDR_EXTRA,
    AOTO_SET_HDR_KEY,
    AOTO_SET_HDR_PATH,
    AOTO_WORKERS,
    COLORS,
)
from .constants import After, Kind
from .model import ActionNode, MenuNode

log = logging.getLogger("aoto")

_lock = threading.RLock()
_groups: dict[str, list[str]] = {}          # group label -> controller addresses
_group_maxima: dict[str, int | None] = {}   # group label -> "@max" from its file (None = unset)
_commands: list[dict] = []                  # command defs from commands.json
# (group, command label) -> per-controller results [(addr, ok, value), ...]
_status: dict[tuple[str, str], list[tuple[str, bool, object]]] = {}
_step: int = AOTO_BRIGHTNESS_STEP           # AOTO-wide brightness step (×2 / ÷2 buttons)


# --- catalog (read from disk) ---------------------------------------------
def refresh() -> None:
    """Reload groups (+ per-group maxima) and commands from disk. Call on start/reload."""
    global _groups, _group_maxima, _commands
    groups, maxima = _load_groups_and_maxima()
    commands = _load_commands()
    with _lock:
        _groups = groups
        _group_maxima = maxima
        _commands = commands


def _group_label(stem: str) -> str:
    return re.sub(r"^\d+[_\-\s]*", "", stem) or stem   # strip NN_ ordering prefix


def _parse_group_lines(lines: list[str]) -> tuple[list[str], int | None]:
    """Addresses + the optional '<AOTO_BRIGHTNESS_MAX_DIRECTIVE> = <n>' directive of a group file.

    Lines look like the Touch groups: '#' comments are dropped and a directive
    line ('@max = 1500') sets that group's brightness ceiling; everything else
    that is non-empty is a controller address.
    """
    key = AOTO_BRIGHTNESS_MAX_DIRECTIVE[1:]            # compare without the '@'
    addrs: list[str] = []
    maximum: int | None = None
    for ln in lines:
        ln = ln.split("#", 1)[0].strip()
        if not ln:
            continue
        if ln.startswith("@"):
            name, _, value = ln[1:].partition("=")
            if name.strip().lower() == key.lower() and value.strip().isdigit():
                maximum = int(value.strip())
            continue
        addrs.append(ln)
    return addrs, maximum


def _load_groups_and_maxima() -> tuple[dict[str, list[str]], dict[str, int | None]]:
    groups: dict[str, list[str]] = {}
    maxima: dict[str, int | None] = {}
    try:
        files = sorted(p for p in AOTO_GROUPS_DIR.iterdir() if p.suffix.lower() == ".txt")
    except FileNotFoundError:
        return groups, maxima
    except Exception as e:  # noqa: BLE001
        log.warning("aoto groups dir unreadable: %s", e)
        return groups, maxima
    for p in files:
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception as e:  # noqa: BLE001
            log.warning("aoto group %s unreadable: %s", p.name, e)
            continue
        addrs, maximum = _parse_group_lines(lines)
        label = _group_label(p.stem)
        groups[label] = addrs
        maxima[label] = maximum
    return groups, maxima


def _load_groups() -> dict[str, list[str]]:
    """Controller addresses per group (kept for callers/tests that want just the list)."""
    return _load_groups_and_maxima()[0]


def _load_commands() -> list[dict]:
    try:
        data = json.loads(AOTO_COMMANDS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception as e:  # noqa: BLE001 - missing/invalid config must not crash
        log.warning("aoto commands.json unreadable/invalid: %s", e)
        return []
    return [c for c in data if isinstance(c, dict) and c.get("label")]


def groups() -> list[str]:
    with _lock:
        return list(_groups)


def addresses(group: str) -> list[str]:
    with _lock:
        return list(_groups.get(group, []))


def commands() -> list[dict]:
    with _lock:
        return list(_commands)


def _cached_results(group: str, label: str) -> list[tuple[str, bool, object]]:
    with _lock:
        return list(_status.get((group, label), []))


# --- HTTP -----------------------------------------------------------------
def _request(addr: str, cmd: dict) -> tuple[bool, object]:
    """Send one command to one controller. Returns (ok, value_or_None)."""
    url = f"http://{addr}{cmd.get('path', '')}"
    body = cmd.get("body")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json;charset=UTF-8", "token": ""}
    headers.update(cmd.get("headers") or {})   # per-command override (e.g. a real token)
    req = urllib.request.Request(
        url, data=data, method=(cmd.get("method") or "POST").upper(), headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=AOTO_HTTP_TIMEOUT) as resp:
            text = resp.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - unreachable/timeout/HTTP error
        return (False, None)
    field = cmd.get("response_field")
    return (True, _extract(text, field) if field else None)


def _extract(text: str, field: str):
    """Pull a dotted field (e.g. 'data.type') out of a JSON reply."""
    try:
        obj = json.loads(text)
    except Exception:  # noqa: BLE001
        return text.strip()[:12]
    for part in field.split("."):
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return None
    return obj


def _run(group: str, cmd: dict) -> list[tuple[str, bool, object]]:
    """Fire a command at every controller in the group; return per-controller results."""
    addrs = addresses(group)
    if not addrs:
        return []
    with ThreadPoolExecutor(max_workers=AOTO_WORKERS) as ex:
        pairs = list(ex.map(lambda a: _request(a, cmd), addrs))
    return [(a, ok, v) for a, (ok, v) in zip(addrs, pairs)]


def run_group(group: str, cmd: dict) -> str:
    """Action command: fire at the whole group, return an OK/ERR summary line."""
    if not addresses(group):
        return "нет адресов"
    return _action_text(_run(group, cmd))


# --- public seams for the preset browser (core/aotopresets.py) -------------
def fire(group: str, cmd: dict) -> bool:
    """Fire {method, path, body} at every controller; True when all replied ok."""
    results = _run(group, cmd)
    return bool(results) and all(ok for _a, ok, _v in results)


def probe(group: str, cmd: dict) -> list[tuple[str, bool, object]]:
    """Read a command with a response_field from every controller: (addr, ok, value) pairs."""
    return list(_run(group, cmd))


def _action_text(results: list[tuple[str, bool, object]]) -> str:
    n = len(results)
    n_ok = sum(1 for _a, ok, _v in results if ok)
    return f"OK {n_ok}/{n}" if n_ok == n else f"ERR {n - n_ok}/{n}"


# --- status: mapping, display, and per-controller breakdown ---------------
def _map(cmd: dict, value) -> object:
    """Map a raw value through the command's 'labels' (e.g. 2 -> 'HLG'), if any."""
    labels = cmd.get("labels")
    return labels.get(str(value), value) if labels else value


def _status_text(cmd: dict, results: list[tuple[str, bool, object]]) -> str:
    """Aggregated status for a group: value / range / list, with a (k/n) on partial."""
    n = len(results)
    n_ok = sum(1 for _a, ok, _v in results if ok)
    vals = [_map(cmd, v) for _a, ok, v in results if ok and v is not None]
    if not vals:
        return "ERR"
    shown = _format_values(vals)
    return shown if n_ok == n else f"{shown} ({n_ok}/{n})"


def _values_differ(cmd: dict, results: list[tuple[str, bool, object]]) -> bool:
    seen = {_num(_map(cmd, v)) for _a, ok, v in results if ok and v is not None}
    return len(seen) > 1


def _format_values(vals: list) -> str:
    """One value if the group agrees; a min-max range if numbers differ; else a list."""
    distinct = list(dict.fromkeys(vals))            # unique, order-preserving
    if len(distinct) == 1:
        return _num(distinct[0])
    nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(nums) == len(vals):                      # all numeric -> range shows the spread
        return f"{_num(min(nums))}-{_num(max(nums))}"
    return "/".join(_num(v) for v in distinct)      # categorical -> list distinct values


def _num(x) -> str:
    return str(int(x)) if isinstance(x, float) and x.is_integer() else str(x)


# --- background status poller ---------------------------------------------
def _poll_statuses() -> None:
    for group in groups():
        for cmd in commands():
            if not cmd.get("response_field"):
                continue
            results = _run(group, cmd)
            with _lock:
                _status[(group, cmd["label"])] = results


def start(on_update) -> None:
    """Background poller for status commands. `on_update` redraws the deck."""

    def loop():
        while True:
            _poll_statuses()
            try:
                on_update()
            except Exception as e:  # noqa: BLE001
                log.warning("aoto on_update failed: %s", e)
            time.sleep(AOTO_POLL_INTERVAL)

    threading.Thread(target=loop, name="aoto-poller", daemon=True).start()


# --- menu tree (providers) -------------------------------------------------
def attach(root: MenuNode) -> None:
    """Insert the AOTO menu after the ПК/PDQ tabs on the main menu."""
    idx = 0
    for i, child in enumerate(root.children):
        if getattr(child, "name", "") in ("__pc__", "__pdq__"):
            idx = i + 1
    root.children.insert(
        idx, MenuNode(name="__aoto__", path=None, label="AOTO", provider=_aoto_children)
    )


def _aoto_children(node) -> list:
    return [
        MenuNode(name=g, path=None, label=g, provider=_group_commands, context={"group": g})
        for g in groups()
    ]


def _green():
    return COLORS[Kind.FEEDBACK]


def _command_by_label(label: str) -> dict | None:
    return next((c for c in commands() if c.get("label") == label), None)


def _group_agreed_value(group: str, status_label: str):
    """The single value all controllers report for a status, or None if they differ."""
    vals = {v for _a, ok, v in _cached_results(group, status_label) if ok and v is not None}
    return next(iter(vals)) if len(vals) == 1 else None


def _active_color(group: str, status_label: str, value):
    """Green when the group's current state equals this button's value, else default."""
    return COLORS[Kind.FEEDBACK] if _group_agreed_value(group, status_label) == value else None


def _apply_tracked(group: str, cmd: dict) -> str:
    run_group(group, cmd)                                   # apply the change
    tracker = _command_by_label(cmd.get("active_status"))
    if tracker:
        _press_status(group, tracker)                       # re-poll so the highlight is truthful
    return ""


def _group_commands(node) -> list:
    group = node.context["group"]
    out: list = []
    for cmd in commands():
        if cmd.get("hidden"):                  # polled for state only, never shown
            continue
        label = cmd["label"]
        if not cmd.get("response_field"):      # action button: fire and show result
            active = cmd.get("active_status")
            if active is not None:             # highlight when the group is in this state
                out.append(ActionNode(
                    name=label, label=label, kind=Kind.COMMAND, after=After.RERENDER,
                    on_press=lambda g=group, c=cmd: _apply_tracked(g, c),
                    color_fn=lambda g=group, s=active, v=cmd.get("active_value"): _active_color(g, s, v),
                ))
            else:
                out.append(ActionNode(
                    name=label, label=label, kind=Kind.COMMAND, after=After.TEXT,
                    on_press=lambda g=group, c=cmd: run_group(g, c),
                ))
            continue
        # status button: value from cache; if the group disagrees, drill into a
        # per-controller breakdown, else press re-polls.
        results = _cached_results(group, label)
        text = _status_text(cmd, results) if results else ""
        display = f"{label}\n{text}" if text else label
        if _values_differ(cmd, results):
            out.append(MenuNode(
                name=label, path=None, label=display, provider=_status_detail,
                context={"group": group, "cmd": cmd}, color_fn=_green,
            ))
        else:
            out.append(ActionNode(
                name=label, label=display, kind=Kind.COMMAND, after=After.RERENDER,
                on_press=lambda g=group, c=cmd: _press_status(g, c), color_fn=_green,
            ))
    if _command_by_label(AOTO_BRIGHTNESS_STATUS_LABEL):   # brightness control submenu
        out.append(MenuNode(
            name="__brightness__", path=None, label="Управление\nяркостью",
            provider=_brightness_children, context={"group": group},
        ))
    if _command_by_label(AOTO_HDR_STATUS_LABEL):          # dynamic-range control submenu
        out.append(MenuNode(
            name="__hdr__", path=None, label="Dynamic\nRange",
            provider=_hdr_children, context={"group": group},
        ))
    from . import aotopresets          # local import: aotopresets imports this module
    node = aotopresets.group_presets_node(group)
    if node is not None:
        out.append(node)
    return out


def _status_detail(node) -> list:
    """One button per controller: its IP's last octet and that controller's value."""
    group, cmd = node.context["group"], node.context["cmd"]
    out: list = []
    for addr, ok, value in _cached_results(group, cmd["label"]):
        octet = addr.split(":", 1)[0].rsplit(".", 1)[-1]
        shown = _num(_map(cmd, value)) if ok and value is not None else "ERR"
        out.append(ActionNode(
            name=addr, label=f".{octet}\n{shown}", kind=Kind.COMMAND,
            after=After.RERENDER, color_fn=_green,
            on_press=lambda g=group, c=cmd: _press_status(g, c),  # re-poll to refresh
        ))
    return out


def _press_status(group: str, cmd: dict) -> str:
    results = _run(group, cmd)
    with _lock:
        _status[(group, cmd["label"])] = results
    return ""   # After.RERENDER redraws the label(s) from the cache


# --- brightness control ----------------------------------------------------
def get_step() -> int:
    with _lock:
        return _step


def _scale_step(factor: float) -> str:
    """Double / halve the AOTO-wide step (floored at 1)."""
    global _step
    with _lock:
        _step = max(1, int(_step * factor))
    return ""   # After.RERENDER redraws the step label


def brightness_limit(group: str) -> int:
    """Brightness ceiling for a group: its '@max' file directive if set, else the
    per-group config override, else the default."""
    with _lock:
        file_max = _group_maxima.get(group)
    if file_max is not None:
        return file_max
    return AOTO_BRIGHTNESS_LIMITS.get(group, AOTO_BRIGHTNESS_LIMIT_DEFAULT)


def _percent_step(limit: int) -> int:
    """Step of the "Темнее/Ярче 5%" buttons: AOTO_BRIGHTNESS_PERCENT % of the limit."""
    return max(1, round(limit * AOTO_BRIGHTNESS_PERCENT / 100))


def _set_brightness_cmd(value: int) -> dict:
    return {"method": "POST", "path": AOTO_SET_BRIGHTNESS_PATH,
            "body": {AOTO_SET_BRIGHTNESS_KEY: value}}


def _adjust_brightness_by(group: str, sign: int, step: int) -> str:
    """Read each controller's brightness, shift by `sign * step`, clamp, write back."""
    read_cmd = _command_by_label(AOTO_BRIGHTNESS_STATUS_LABEL)
    addrs = addresses(group)
    if read_cmd is None or not addrs:
        return ""
    limit = brightness_limit(group)

    def adjust_one(addr: str) -> None:
        ok, cur = _request(addr, read_cmd)
        if not ok or not isinstance(cur, (int, float)) or isinstance(cur, bool):
            return                                   # unreachable / non-numeric -> skip
        target = max(AOTO_BRIGHTNESS_MIN, min(limit, int(cur) + sign * step))
        _request(addr, _set_brightness_cmd(target))

    with ThreadPoolExecutor(max_workers=AOTO_WORKERS) as ex:
        list(ex.map(adjust_one, addrs))
    _press_status(group, read_cmd)                   # refresh the shown value
    return ""   # After.RERENDER


def _adjust_brightness(group: str, sign: int) -> str:
    """+/- by the manual step (get_step)."""
    return _adjust_brightness_by(group, sign, get_step())


def _adjust_brightness_pct(group: str, sign: int) -> str:
    """+/- by 5% of the group maximum (the '@max' file directive or config)."""
    return _adjust_brightness_by(group, sign, _percent_step(brightness_limit(group)))


def _brightness_children(node) -> list:
    """The "Управление яркостью" submenu: current value, +/- (manual step and 5% of max),
    and the manual-step controls."""
    group = node.context["group"]
    step = get_step()
    status = _command_by_label(AOTO_BRIGHTNESS_STATUS_LABEL)
    out: list = []
    if status:                                       # current brightness; press re-polls
        results = _cached_results(group, status["label"])
        text = _status_text(status, results) if results else ""
        out.append(ActionNode(
            name="brightness", label=f"Яркость\n{text}" if text else "Яркость",
            kind=Kind.COMMAND, after=After.RERENDER, color_fn=_green,
            on_press=lambda g=group, c=status: _press_status(g, c),
        ))
    out.append(ActionNode(
        name="down", label="Темнее", kind=Kind.COMMAND, after=After.RERENDER,
        on_press=lambda g=group: _adjust_brightness(g, -1),
    ))
    out.append(ActionNode(
        name="up", label="Ярче", kind=Kind.COMMAND, after=After.RERENDER,
        on_press=lambda g=group: _adjust_brightness(g, +1),
    ))
    out.append(ActionNode(
        name="down5", label="Темнее 5%", kind=Kind.COMMAND, after=After.RERENDER,
        on_press=lambda g=group: _adjust_brightness_pct(g, -1),
    ))
    out.append(ActionNode(
        name="up5", label="Ярче 5%", kind=Kind.COMMAND, after=After.RERENDER,
        on_press=lambda g=group: _adjust_brightness_pct(g, +1),
    ))
    out.append(ActionNode(
        name="step-half", label="Шаг ÷2", kind=Kind.COMMAND, after=After.RERENDER,
        on_press=lambda: _scale_step(0.5),
    ))
    out.append(ActionNode(
        name="step", label=f"Шаг\n{step}", kind=Kind.COMMAND, after=After.RERENDER,
        on_press=lambda: "",                         # info only; just re-renders
    ))
    out.append(ActionNode(
        name="step-double", label="Шаг ×2", kind=Kind.COMMAND, after=After.RERENDER,
        on_press=lambda: _scale_step(2),
    ))
    return out


# --- Dynamic Range (HDR) control -------------------------------------------
def _set_hdr_cmd(value: int) -> dict:
    return {"method": "POST", "path": AOTO_SET_HDR_PATH,
            "body": {AOTO_SET_HDR_KEY: value, **AOTO_SET_HDR_EXTRA}}


def _hdr_children(node) -> list:
    """The "Dynamic Range" submenu: one setter button per mode (SDR/HLG/PQ)."""
    group = node.context["group"]
    return [
        ActionNode(
            name=label, label=label, kind=Kind.COMMAND, after=After.TEXT,
            on_press=lambda g=group, v=value: run_group(g, _set_hdr_cmd(v)),
        )
        for label, value in AOTO_HDR_MODES
    ]
