"""TouchDesigner control: the deck buttons ARE the client's buttons.

The "Touch" tab has no hardcoded content. A TouchDesigner client (any Python
inside a .toe -- see touch/client.example.py) drives the tab over HTTP:

    POST /touch/buttons   {"client": "wall", "label": "Стена",
                           "host": "127.0.0.1", "port": 7777, "address": "/touch",
                           "buttons": [{"id": "intro", "label": "Intro"},
                                       {"id": "clipA", "label": "Клип A", "active": true},
                                       {"id": "black", "label": "Блэкаут", "color": "#4a1414"}]}
    POST /touch/ping      {"client": "wall"}

`host`/`port`/`address` are optional and default to the TOUCH_OSC_* config; the
whole button list is replaced on every POST, so a client simply re-posts when
its buttons change (and pings in between to stay alive).

Every live client becomes a submenu on the Touch tab (`label` above the id), and
pressing one of its buttons fires ONE fire-and-forget OSC message to that
client's host:port/address carrying the button id as a string argument -- the
press is proxied back into TouchDesigner, which reacts however its network does.
The only deck-side buttons are the framework's own Back/Home and paging, so
nothing about the tab is fixed on this side.

Clients must ping: `start` runs a sweeper that drops any client silent for
TOUCH_CLIENT_TIMEOUT seconds and redraws the deck, so a closed .toe never leaves
dead buttons behind. Everything is fail-soft -- core/osc logs its own send
errors, and one invalid button row is skipped with a warning instead of breaking
the rest of the tab. See CLAUDE.md for the conventions.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from . import osc
from .config import (
    COLORS,
    TOUCH_CLIENT_TIMEOUT,
    TOUCH_OSC_ADDRESS,
    TOUCH_OSC_HOST,
    TOUCH_OSC_PORT,
    TOUCH_SWEEP_INTERVAL,
)
from .constants import After, Kind
from .model import ActionNode, MenuNode

log = logging.getLogger("touch")

_FALLBACK_FG = "#ffffff"        # text color on a client-supplied background


@dataclass
class Button:
    """One deck button as the client defines it."""
    id: str                     # sent back to TouchDesigner when pressed
    label: str                  # shown on the deck ("a\nb" = two lines)
    color: str | None = None    # optional "#rrggbb" background
    active: bool = False        # True -> the deck's green "active" highlight


@dataclass
class Client:
    """A registered TouchDesigner client: where to reach it and what it shows."""
    id: str
    label: str
    host: str
    port: int
    address: str
    buttons: list[Button] = field(default_factory=list)
    seen_at: float = 0.0        # monotonic time of the last ping/registration


_lock = threading.RLock()
_clients: dict[str, Client] = {}


def _now() -> float:
    """Monotonic clock (a seam so tests can age a client without sleeping)."""
    return time.monotonic()


# --- payload parsing (pure) -------------------------------------------------
def _clean_text(value, fallback: str = "") -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _clean_color(value) -> str | None:
    """A client color must look like a CSS hex (#rgb / #rrggbb), else it is ignored."""
    color = _clean_text(value)
    if not color:
        return None
    ok = color.startswith("#") and len(color) in (4, 7) and \
        all(c in "0123456789abcdefABCDEF" for c in color[1:])
    if not ok:
        log.warning("touch: ignoring bad color %r", value)
        return None
    return color.lower()


def parse_button(row, source: str = "client") -> Button | None:
    """One client button: {id, label?, color?, active?}. None when unusable."""
    if not isinstance(row, dict):
        return None
    button_id = _clean_text(row.get("id"))
    if not button_id:
        log.warning("touch %s: button without an id was dropped", source)
        return None
    return Button(
        id=button_id,
        label=_clean_text(row.get("label"), button_id),
        color=_clean_color(row.get("color")),
        active=row.get("active") is True,
    )


def parse_buttons(rows, source: str = "client") -> list[Button]:
    """A client's whole button list; rows without an id are skipped."""
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError("buttons must be a list")
    return [b for b in (parse_button(r, source) for r in rows) if b is not None]


# --- the client registry ----------------------------------------------------
def set_buttons(payload: dict) -> dict:
    """Register/refresh a client and REPLACE its buttons (POST /touch/buttons).

    Raises ValueError on a payload that cannot be used, so the HTTP layer can
    answer 400 and the client author sees the problem immediately.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    client_id = _clean_text(payload.get("client"))
    if not client_id:
        raise ValueError("'client' (the client id) is required")
    buttons = parse_buttons(payload.get("buttons"), client_id)
    port = payload.get("port", TOUCH_OSC_PORT)
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ValueError("'port' must be a number") from None
    client = Client(
        id=client_id,
        label=_clean_text(payload.get("label"), client_id),
        host=_clean_text(payload.get("host"), TOUCH_OSC_HOST),
        port=port,
        address=_clean_text(payload.get("address"), TOUCH_OSC_ADDRESS),
        buttons=buttons,
        seen_at=_now(),
    )
    with _lock:
        _clients[client_id] = client
    log.info("touch client %r: %d buttons -> %s:%s%s",
             client_id, len(buttons), client.host, client.port, client.address)
    return {"status": "ok", "client": client_id, "buttons": len(buttons)}


def ping(payload: dict) -> dict:
    """A client heartbeat (POST /touch/ping): keeps its buttons on the deck.

    An unknown client is NOT re-created -- a ping only refreshes a registration,
    so the answer says so and the client re-posts its buttons."""
    client_id = _clean_text(payload.get("client")) if isinstance(payload, dict) else ""
    if not client_id:
        raise ValueError("'client' (the client id) is required")
    with _lock:
        client = _clients.get(client_id)
        if client is not None:
            client.seen_at = _now()
    if client is None:
        log.warning("touch ping from unregistered client %r", client_id)
        return {"status": "unknown", "client": client_id,
                "hint": "POST /touch/buttons first"}
    return {"status": "ok", "client": client_id, "buttons": len(client.buttons)}


def get(client_id: str) -> Client | None:
    with _lock:
        return _clients.get(client_id)


def clients() -> list[Client]:
    """Live clients, ordered by label (the deck submenu order is stable)."""
    with _lock:
        return sorted(_clients.values(), key=lambda c: (c.label.casefold(), c.id))


def expired(now: float | None = None) -> list[str]:
    """Drop clients that have not pinged within TOUCH_CLIENT_TIMEOUT; return their ids."""
    now = _now() if now is None else now
    with _lock:
        dead = [cid for cid, c in _clients.items() if now - c.seen_at > TOUCH_CLIENT_TIMEOUT]
        for cid in dead:
            del _clients[cid]
    for cid in dead:
        log.warning("touch client %r dropped (no ping for %.0fs)", cid, TOUCH_CLIENT_TIMEOUT)
    return dead


def start(on_update) -> None:
    """Drop dead clients and redraw the deck when one disappears."""

    def loop():
        while True:
            try:
                if expired():
                    on_update()
            except Exception as e:  # noqa: BLE001 - the sweeper must never die
                log.warning("touch sweep failed: %s", e)
            time.sleep(TOUCH_SWEEP_INTERVAL)

    threading.Thread(target=loop, name="touch-sweeper", daemon=True).start()


# --- press: proxy the button back into TouchDesigner -----------------------
def press(client_id: str, button_id: str) -> str:
    """Fire the button id at the client over OSC; returns the button's result text."""
    client = get(client_id)
    if client is None:
        return "ERR\nнет клиента"
    osc.send_to(client.host, client.port, client.address, button_id)
    log.info("touch press %r -> %s:%s%s", button_id, client.host, client.port, client.address)
    return "OK"


# --- menu tree (providers; read the registry only) --------------------------
def attach(root: MenuNode) -> None:
    """Insert the Touch menu after the ПК/PDQ/AOTO tabs on the main menu."""
    idx = 0
    for i, child in enumerate(root.children):
        if getattr(child, "name", "") in ("__pc__", "__pdq__", "__aoto__"):
            idx = i + 1
    root.children.insert(
        idx, MenuNode(name="__touch__", path=None, label="Touch", provider=_touch_children)
    )


def button_color(button: Button):
    """A client button's deck color: green when active, else its own background."""
    if button.active:
        return COLORS[Kind.FEEDBACK]
    return (button.color, _FALLBACK_FG) if button.color else None


def _touch_children(node) -> list:
    live = clients()
    if not live:
        return [ActionNode(name="__none__", label="Touch\nнет клиентов",
                           kind=Kind.COMMAND, after=After.TEXT, on_press=lambda: "")]
    return [
        MenuNode(name=c.id, path=None, label=c.label, provider=_client_buttons,
                 context={"client": c.id})
        for c in live
    ]


def _client_buttons(node) -> list:
    client = get(node.context["client"])
    if client is None:              # expired between the render and the press
        return []
    return [
        ActionNode(
            name=b.id, label=b.label, kind=Kind.COMMAND, after=After.TEXT,
            on_press=lambda cid=client.id, bid=b.id: press(cid, bid),
            color_fn=lambda b=b: button_color(b),
        )
        for b in client.buttons
    ]
