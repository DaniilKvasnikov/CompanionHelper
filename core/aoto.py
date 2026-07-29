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
    AOTO_COMMANDS_FILE,
    AOTO_GROUPS_DIR,
    AOTO_HTTP_TIMEOUT,
    AOTO_POLL_INTERVAL,
    AOTO_WORKERS,
    COLORS,
)
from .constants import After, Kind
from .model import ActionNode, MenuNode

log = logging.getLogger("aoto")

_lock = threading.RLock()
_groups: dict[str, list[str]] = {}          # group label -> controller addresses
_commands: list[dict] = []                  # command defs from commands.json
# (group, command label) -> per-controller results [(addr, ok, value), ...]
_status: dict[tuple[str, str], list[tuple[str, bool, object]]] = {}


# --- catalog (read from disk) ---------------------------------------------
def refresh() -> None:
    """Reload groups + commands from disk. Call on start/reload."""
    global _groups, _commands
    groups = _load_groups()
    commands = _load_commands()
    with _lock:
        _groups = groups
        _commands = commands


def _group_label(stem: str) -> str:
    return re.sub(r"^\d+[_\-\s]*", "", stem) or stem   # strip NN_ ordering prefix


def _load_groups() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    try:
        files = sorted(p for p in AOTO_GROUPS_DIR.iterdir() if p.suffix.lower() == ".txt")
    except FileNotFoundError:
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("aoto groups dir unreadable: %s", e)
        return out
    for p in files:
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception as e:  # noqa: BLE001
            log.warning("aoto group %s unreadable: %s", p.name, e)
            continue
        addrs = [a for a in (ln.split("#", 1)[0].strip() for ln in lines) if a]
        out[_group_label(p.stem)] = addrs
    return out


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


def _group_commands(node) -> list:
    group = node.context["group"]
    out: list = []
    for cmd in commands():
        label = cmd["label"]
        if not cmd.get("response_field"):      # action button: fire and show result
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
