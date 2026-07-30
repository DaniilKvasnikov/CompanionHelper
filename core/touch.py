"""TouchDesigner control over OSC, as a dynamic main-menu tab.

A "Touch" button on the main menu opens a list of groups. Each group is a file
in touch/groups/ listing buttons, one "label = filename" per line. Selecting a
group opens its buttons; pressing a button fires a single OSC message to
TouchDesigner (TOUCH_OSC_HOST:TOUCH_OSC_PORT) at TOUCH_OSC_ADDRESS with the
button's filename as a string argument.

Groups organize buttons only: every button targets the same OSC destination and
address, differing only by the filename it sends. This module owns the group
catalog (read from disk on start/reload); pressing sends fire-and-forget OSC.
See CLAUDE.md for the conventions.
"""
from __future__ import annotations

import logging
import re
import threading

from . import osc
from .config import TOUCH_GROUPS_DIR, TOUCH_OSC_ADDRESS, TOUCH_OSC_HOST, TOUCH_OSC_PORT
from .constants import After, Kind
from .model import ActionNode, MenuNode

log = logging.getLogger("touch")

_lock = threading.RLock()
_groups: dict[str, list[tuple[str, str]]] = {}   # group label -> [(button label, filename), ...]


# --- catalog (read from disk) ---------------------------------------------
def refresh() -> None:
    """Reload groups from disk. Call on start/reload."""
    global _groups
    groups = _load_groups()
    with _lock:
        _groups = groups


def _group_label(stem: str) -> str:
    return re.sub(r"^\d+[_\-\s]*", "", stem) or stem   # strip NN_ ordering prefix


def _load_groups() -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = {}
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
        buttons_: list[tuple[str, str]] = []
        for ln in lines:
            ln = ln.split("#", 1)[0].strip()
            if not ln or "=" not in ln:
                continue
            label, filename = (s.strip() for s in ln.split("=", 1))
            if label and filename:
                buttons_.append((label, filename))
        out[_group_label(p.stem)] = buttons_
    return out


def groups() -> list[str]:
    with _lock:
        return list(_groups)


def buttons(group: str) -> list[tuple[str, str]]:
    with _lock:
        return list(_groups.get(group, []))


# --- OSC send -------------------------------------------------------------
def send_file(filename: str) -> str:
    """Fire the filename to TouchDesigner over OSC. Returns a short button line."""
    osc.send_to(TOUCH_OSC_HOST, TOUCH_OSC_PORT, TOUCH_OSC_ADDRESS, filename)
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
    return [
        MenuNode(name=g, path=None, label=g, provider=_group_buttons, context={"group": g})
        for g in groups()
    ]


def _group_buttons(node) -> list:
    group = node.context["group"]
    return [
        ActionNode(
            name=label, label=label, kind=Kind.COMMAND, after=After.TEXT,
            on_press=lambda f=filename: send_file(f),
        )
        for label, filename in buttons(group)
    ]
