"""TouchDesigner control over OSC, as a dynamic main-menu tab.

A "Touch" button on the main menu opens a list of groups. Each group is a file
in touch/groups/ listing buttons, one "label = filename" per line. Selecting a
group opens its buttons; pressing a button fires a single OSC message to
TouchDesigner (TOUCH_OSC_HOST:TOUCH_OSC_PORT) with the button's filename as a
string argument.

Each group has its own OSC address, so different groups (стена, потолок, …) can
target different things in TouchDesigner. A group file may set it with a
directive line:

    @address = /wall        # this group's OSC address (default: TOUCH_OSC_ADDRESS)
    Intro = intro.tox       # a button
    Клип A = clipA.mov

Without an @address line the group falls back to TOUCH_OSC_ADDRESS.

The Touch tab also has top-level buttons (TOUCH_COMMANDS: file/base/fps),
alongside the groups, that each fire a *no-argument* OSC message to an address
named after them (e.g. "file" -> /file).

This module owns the group catalog (read from disk on start/reload); pressing
sends fire-and-forget OSC. See CLAUDE.md for the conventions.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field

from . import osc
from .config import (
    TOUCH_COMMANDS,
    TOUCH_GROUPS_DIR,
    TOUCH_OSC_ADDRESS,
    TOUCH_OSC_HOST,
    TOUCH_OSC_PORT,
)
from .constants import After, Kind
from .model import ActionNode, MenuNode

log = logging.getLogger("touch")


@dataclass
class _Group:
    address: str                                    # OSC address for this group's buttons
    buttons: list[tuple[str, str]] = field(default_factory=list)   # [(label, filename), ...]


_lock = threading.RLock()
_groups: dict[str, _Group] = {}                     # group label -> _Group


# --- catalog (read from disk) ---------------------------------------------
def refresh() -> None:
    """Reload groups from disk. Call on start/reload."""
    global _groups
    groups = _load_groups()
    with _lock:
        _groups = groups


def _group_label(stem: str) -> str:
    return re.sub(r"^\d+[_\-\s]*", "", stem) or stem   # strip NN_ ordering prefix


def _load_groups() -> dict[str, _Group]:
    out: dict[str, _Group] = {}
    try:
        files = sorted(p for p in TOUCH_GROUPS_DIR.iterdir() if p.suffix.lower() == ".txt")
    except FileNotFoundError:
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("touch groups dir unreadable: %s", e)
        return out
    for p in files:
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception as e:  # noqa: BLE001
            log.warning("touch group %s unreadable: %s", p.name, e)
            continue
        out[_group_label(p.stem)] = _parse_group(lines)
    return out


def _parse_group(lines: list[str]) -> _Group:
    group = _Group(address=TOUCH_OSC_ADDRESS)
    for ln in lines:
        ln = ln.split("#", 1)[0].strip()
        if not ln:
            continue
        if ln.startswith("@"):                       # directive, e.g. "@address = /wall"
            key, _, val = ln[1:].partition("=")
            if key.strip().lower() == "address" and val.strip():
                group.address = val.strip()
            continue
        if "=" not in ln:
            continue
        label, filename = (s.strip() for s in ln.split("=", 1))
        if label and filename:
            group.buttons.append((label, filename))
    return group


def groups() -> list[str]:
    with _lock:
        return list(_groups)


def buttons(group: str) -> list[tuple[str, str]]:
    with _lock:
        g = _groups.get(group)
        return list(g.buttons) if g else []


def address(group: str) -> str:
    with _lock:
        g = _groups.get(group)
        return g.address if g else TOUCH_OSC_ADDRESS


# --- OSC send -------------------------------------------------------------
def send_file(address: str, filename: str) -> str:
    """Fire the filename to TouchDesigner at `address` over OSC. Returns a button line."""
    osc.send_to(TOUCH_OSC_HOST, TOUCH_OSC_PORT, address, filename)
    return "OK"


def send_command(name: str) -> str:
    """Fire a no-argument OSC message to /<name> (e.g. 'file' -> /file)."""
    osc.send_to(TOUCH_OSC_HOST, TOUCH_OSC_PORT, f"/{name}")
    return "OK"


# --- menu tree (providers) -------------------------------------------------
def attach(root: MenuNode) -> None:
    """Insert the Touch menu after the ПК/PDQ/AOTO tabs on the main menu."""
    idx = 0
    for i, child in enumerate(root.children):
        if getattr(child, "name", "") in ("__pc__", "__pdq__", "__aoto__"):
            idx = i + 1
    root.children.insert(
        idx, MenuNode(name="__touch__", path=None, label="Touch", provider=_touch_children)
    )


def _touch_children(node) -> list:
    # Top-level no-argument commands (file/base/fps), then the group menus.
    commands = [
        ActionNode(
            name=cmd, label=cmd, kind=Kind.COMMAND, after=After.TEXT,
            on_press=lambda c=cmd: send_command(c),
        )
        for cmd in TOUCH_COMMANDS
    ]
    menus = [
        MenuNode(name=g, path=None, label=g, provider=_group_buttons, context={"group": g})
        for g in groups()
    ]
    return commands + menus


def _group_buttons(node) -> list:
    group = node.context["group"]
    addr = address(group)
    return [
        ActionNode(
            name=label, label=label, kind=Kind.COMMAND, after=After.TEXT,
            on_press=lambda a=addr, f=filename: send_file(a, f),
        )
        for label, filename in buttons(group)
    ]
