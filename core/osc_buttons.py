"""Arbitrary OSC messages as deck buttons, as a dynamic main-menu tab.

An "OSC" button on the main menu opens a list of groups. Each group is a file
in osc/groups/ listing buttons, one "label = /address arg arg" per line.
Selecting a group opens its buttons; pressing one fires a single OSC message
and shows OK.

This differs from the Touch tab in where the address lives. There, the address
belongs to the group and every button sends its filename to it. Here, each
button carries its own address *and* its own arguments, which is what driving
operator parameters needs:

    @host = 127.0.0.1       # optional, default OSC_BUTTONS_HOST
    @port = 7000            # optional, default OSC_BUTTONS_PORT
    Байпас вкл = /project1/grade/Bypass 1
    Позиция    = /project1/geo1/t 0.5 0 0
    Сброс      = /project1/base1/Reset          # no arguments at all

Arguments are typed by how they parse: "1" is an int, "0.5" a float, anything
else a string; quote to keep spaces together. Nothing is read back — this is
fire-and-forget, like the Touch tab, so there is no poller and no cache.

This module owns the group catalog (read from disk on start/reload). See
CLAUDE.md for the conventions.
"""
from __future__ import annotations

import logging
import re
import shlex
import threading
from dataclasses import dataclass, field

from . import osc
from .config import OSC_BUTTONS_GROUPS_DIR, OSC_BUTTONS_HOST, OSC_BUTTONS_PORT
from .constants import After, Kind
from .model import ActionNode, MenuNode

log = logging.getLogger("osc_buttons")


@dataclass
class _Button:
    label: str
    address: str
    args: tuple = ()


@dataclass
class _Group:
    host: str                                       # OSC destination for this group
    port: int
    buttons: list[_Button] = field(default_factory=list)


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
        files = sorted(
            p for p in OSC_BUTTONS_GROUPS_DIR.iterdir() if p.suffix.lower() == ".txt"
        )
    except FileNotFoundError:
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("osc groups dir unreadable: %s", e)
        return out
    for p in files:
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception as e:  # noqa: BLE001
            log.warning("osc group %s unreadable: %s", p.name, e)
            continue
        out[_group_label(p.stem)] = _parse_group(lines)
    return out


def _typed(token: str):
    """int if it looks like one, else float, else the string as written."""
    for cast in (int, float):
        try:
            return cast(token)
        except ValueError:
            pass
    return token


def _parse_message(text: str) -> tuple[str, tuple] | None:
    """'/project1/geo1/t 0.5 0 0' -> ('/project1/geo1/t', (0.5, 0, 0))."""
    try:
        tokens = shlex.split(text)
    except ValueError as e:                          # unbalanced quotes
        log.warning("osc button %r unparsable: %s", text, e)
        return None
    if not tokens or not tokens[0].startswith("/"):
        return None                                  # an address is mandatory
    return tokens[0], tuple(_typed(t) for t in tokens[1:])


def _parse_group(lines: list[str]) -> _Group:
    group = _Group(host=OSC_BUTTONS_HOST, port=OSC_BUTTONS_PORT)
    for ln in lines:
        ln = ln.split("#", 1)[0].strip()
        if not ln:
            continue
        if ln.startswith("@"):                       # directive, e.g. "@port = 7000"
            key, _, val = ln[1:].partition("=")
            key, val = key.strip().lower(), val.strip()
            if key == "host" and val:
                group.host = val
            elif key == "port" and val:
                try:
                    group.port = int(val)
                except ValueError:
                    log.warning("osc group @port %r is not a number", val)
            continue
        if "=" not in ln:
            continue
        label, message = (s.strip() for s in ln.split("=", 1))
        if not label or not message:
            continue
        parsed = _parse_message(message)
        if parsed is None:
            log.warning("osc button %r has no leading /address, skipped", label)
            continue
        group.buttons.append(_Button(label=label, address=parsed[0], args=parsed[1]))
    return group


def groups() -> list[str]:
    with _lock:
        return list(_groups)


def buttons(group: str) -> list[_Button]:
    with _lock:
        g = _groups.get(group)
        return list(g.buttons) if g else []


def target(group: str) -> tuple[str, int]:
    with _lock:
        g = _groups.get(group)
        return (g.host, g.port) if g else (OSC_BUTTONS_HOST, OSC_BUTTONS_PORT)


# --- OSC send -------------------------------------------------------------
def send(host: str, port: int, address: str, args=()) -> str:
    """Fire one message at host:port. Returns a button line."""
    osc.send_to(host, port, address, *args)
    return "OK"


# --- menu tree (providers) -------------------------------------------------
def attach(root: MenuNode) -> None:
    """Insert the OSC menu after the ПК/PDQ/AOTO/Touch tabs on the main menu."""
    idx = 0
    for i, child in enumerate(root.children):
        if getattr(child, "name", "") in ("__pc__", "__pdq__", "__aoto__", "__touch__"):
            idx = i + 1
    root.children.insert(
        idx, MenuNode(name="__osc__", path=None, label="OSC", provider=_osc_children)
    )


def _osc_children(node) -> list:
    return [
        MenuNode(name=g, path=None, label=g, provider=_group_buttons, context={"group": g})
        for g in groups()
    ]


def _group_buttons(node) -> list:
    group = node.context["group"]
    host, port = target(group)
    return [
        ActionNode(
            name=b.label, label=b.label, kind=Kind.COMMAND, after=After.TEXT,
            on_press=lambda h=host, p=port, a=b.address, v=b.args: send(h, p, a, v),
        )
        for b in buttons(group)
    ]
