"""Dynamic "PC" menu built from the active PDQ target list.

Main menu gets a "PC" button. Inside:
  - a "change list" button -> submenu of all target lists (pick -> back);
  - one button per PC in the active list, colored by ping (green/red/gray);
  - selecting a PC opens a menu of packages; pressing a package deploys it
    to that single PC.

The target-list / package names come from the PDQ database (cached here so
providers never hit the DB per render); ping status is refreshed by a
background sweep. See core/pdq.py for the DB + deploy details.
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import pdq
from .runner import RunResult
from .config import (
    COLORS,
    PC_ALIASES_FILE,
    PC_DOWN,
    PC_UNKNOWN,
    PC_UP,
    PING_INTERVAL,
    PING_TIMEOUT_MS,
    PING_WORKERS,
)
from .constants import After, Kind
from .model import ActionNode, MenuNode

log = logging.getLogger("pcbrowser")

_lock = threading.RLock()
_active_list: str | None = None          # None -> use the first list
_lists: list[str] = []                    # all target-list names (cached)
_packages: list[str] = []                 # all package names (cached)
_members: dict[str, list[str]] = {}       # list name -> hosts (cached)
_ping: dict[str, bool] = {}               # host -> reachable
_aliases: dict[str, str] = {}             # host/ip -> display alias (from file)


# --- cached catalog (read from the PDQ DB) --------------------------------
def refresh_catalog() -> None:
    """Reload target-list / package names from the DB and PC aliases from disk."""
    global _lists, _packages, _aliases
    aliases = _load_aliases()
    with _lock:
        _aliases = aliases
    try:
        lists = pdq.list_target_lists()
        packages = pdq.list_packages()
    except Exception as e:  # noqa: BLE001
        log.warning("catalog refresh failed: %s", e)
        return
    with _lock:
        _lists = lists
        _packages = packages
    _refresh_members()


def _load_aliases() -> dict[str, str]:
    """Read the optional 'ip = alias' file; missing/invalid lines are skipped."""
    out: dict[str, str] = {}
    try:
        lines = PC_ALIASES_FILE.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("pc aliases unreadable: %s", e)
        return out
    for ln in lines:
        ln = ln.split("#", 1)[0].strip()
        if "=" not in ln:
            continue
        ip, name = (s.strip() for s in ln.split("=", 1))
        if ip and name:
            out[ip] = name
    return out


def alias(host: str) -> str | None:
    with _lock:
        return _aliases.get(host)


def host_label(host: str) -> str:
    """Deck label for a host: the alias above the ip if aliased, else the raw host."""
    name = alias(host)
    return f"{name}\n{host}" if name else host


def _host_sort_key(host: str):
    name = alias(host)
    return (0, name.casefold()) if name else (1, host)  # aliased first, sorted by alias


def _refresh_members() -> None:
    name = active_list()
    if not name:
        return
    try:
        hosts = pdq.target_list_members(name)
    except Exception as e:  # noqa: BLE001
        log.warning("members refresh failed for %r: %s", name, e)
        return
    with _lock:
        _members[name] = hosts


def active_list() -> str | None:
    with _lock:
        if _active_list and _active_list in _lists:
            return _active_list
        return _lists[0] if _lists else None


def lists() -> list[str]:
    with _lock:
        return list(_lists)


def packages() -> list[str]:
    with _lock:
        return list(_packages)


def members() -> list[str]:
    name = active_list()
    with _lock:
        hosts = list(_members.get(name, [])) if name else []
    return sorted(hosts, key=_host_sort_key)  # aliased first (by alias), then by host


def set_active(name: str) -> None:
    global _active_list
    with _lock:
        _active_list = name
    _refresh_members()


# --- ping ------------------------------------------------------------------
def _ping_host(host: str) -> bool:
    try:
        proc = subprocess.run(
            ["ping", "-n", "1", "-w", str(PING_TIMEOUT_MS), host],
            capture_output=True,
            text=True,
            timeout=PING_TIMEOUT_MS / 1000 + 2,
        )
        # returncode 0 alone is unreliable on Windows; require an actual reply.
        return "TTL=" in proc.stdout.upper()
    except Exception:  # noqa: BLE001
        return False


def _ping_sweep() -> None:
    hosts = members()
    if not hosts:
        return
    with ThreadPoolExecutor(max_workers=PING_WORKERS) as ex:
        results = dict(zip(hosts, ex.map(_ping_host, hosts)))
    with _lock:
        _ping.update(results)


def pc_color(host: str):
    with _lock:
        status = _ping.get(host)
    if status is True:
        return PC_UP
    if status is False:
        return PC_DOWN
    return PC_UNKNOWN


def start(on_update) -> None:
    """Background ping loop. `on_update` redraws pages so colors update live."""

    def loop():
        while True:
            try:
                _ping_sweep()
            except Exception as e:  # noqa: BLE001 - never let the pinger die
                log.warning("ping sweep failed: %s", e)
            try:
                on_update()
            except Exception as e:  # noqa: BLE001
                log.warning("ping on_update failed: %s", e)
            time.sleep(PING_INTERVAL)

    threading.Thread(target=loop, name="pinger", daemon=True).start()


# --- menu tree (providers) -------------------------------------------------
def attach(root: MenuNode) -> None:
    """Insert the PC menu at the top of the main menu."""
    root.children.insert(0, MenuNode(name="__pc__", path=None, label="ПК", provider=_pc_children))


def _pc_children(node) -> list:
    current = active_list() or "-"
    kids: list = [
        MenuNode(
            name="__changelist__",
            path=None,
            label=f"Лист:\n{current}",
            provider=list_picker,
            color_fn=lambda: COLORS[Kind.NAV],
        )
    ]
    for host in members():
        kids.append(
            MenuNode(
                name=host,
                path=None,
                label=host_label(host),
                provider=_pc_packages,
                context={"host": host},
                color_fn=lambda h=host: pc_color(h),
            )
        )
    return kids


def _select_list(name: str) -> str:
    set_active(name)
    return ""


def list_picker(node) -> list:
    """Submenu: one button per target list; picking it sets the active list.

    Shared by the "ПК" menu and the PDQ batch menu (core/pdqmenu.py)."""
    current = active_list()
    out: list = []
    for name in lists():
        label = ("* " if name == current else "") + name
        out.append(
            ActionNode(
                name=name,
                label=label,
                kind=Kind.MENU,
                after=After.BACK,
                on_press=lambda n=name: _select_list(n),
            )
        )
    return out


def _pc_packages(node) -> list:
    host = node.context["host"]
    return [
        ActionNode(
            name=pkg,
            label=pkg,
            kind=Kind.COMMAND,
            on_press=lambda p=pkg, h=host: _deploy(p, h),
        )
        for pkg in packages()
    ]


def _deploy(package: str, host: str) -> str:
    return RunResult(*pdq.run(pdq.deploy_args(package, [host]))).summary()
