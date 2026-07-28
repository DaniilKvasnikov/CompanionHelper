"""Thin client over Companion's HTTP API. Only touches button visuals.

Uses one persistent Session (keep-alive, no reconnect per button) and pushes
styles in parallel so redrawing a full page isn't 32 serial round-trips.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import requests

from . import osc
from .config import COMPANION_URL, CONNECT_TIMEOUT, READ_TIMEOUT, RENDER_WORKERS

log = logging.getLogger("companion")

# Fast path: change only a button's text over OSC/UDP (no round-trip).
set_text = osc.set_text

_session = requests.Session()
_pool = ThreadPoolExecutor(max_workers=RENDER_WORKERS, thread_name_prefix="companion")
_TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)


def set_style(page, row, col, text="", bgcolor="#000000", color="#ffffff") -> None:
    """Set one button's text/colors. Fails soft: logs and continues on error."""
    url = f"{COMPANION_URL}/{page}/{row}/{col}/style"
    try:
        _session.post(
            url,
            params={"text": text, "bgcolor": bgcolor, "color": color},
            json={},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        log.warning("style %s/%s/%s failed: %s", page, row, col, e)


def clear(page, row, col) -> None:
    set_style(page, row, col, text="", bgcolor="#000000", color="#000000")


def apply(updates) -> None:
    """Push many (page, row, col, text, bgcolor, color) styles in parallel."""
    futures = [_pool.submit(set_style, *u) for u in updates]
    for f in futures:  # wait so the deck is fully drawn before we return
        f.result()
