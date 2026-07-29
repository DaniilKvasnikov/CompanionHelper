"""Countdown to the next auto-refresh, published as a Companion custom variable.

A button that shows `$(custom:Progress)` displays the whole seconds left until
the next feedback poll. A daemon thread ticks once a second; the feedback poller
calls `mark()` at the end of each cycle so the countdown stays in sync with the
real refresh cadence (rather than free-running and drifting).

Companion custom variables are global, so the value is the same on every page —
put `$(custom:Progress)` only where an auto-updating page makes it meaningful.
"""
from __future__ import annotations

import logging
import threading
import time

from . import companion
from .config import FEEDBACK_INTERVAL, PROGRESS_TICK, PROGRESS_VAR

log = logging.getLogger("progress")

_interval = FEEDBACK_INTERVAL
_next_due = time.monotonic() + FEEDBACK_INTERVAL


def mark(interval: float | None = None) -> None:
    """Reset the countdown: the next refresh is `interval` seconds from now."""
    global _interval, _next_due
    if interval is not None:
        _interval = interval
    _next_due = time.monotonic() + _interval


def remaining() -> int:
    """Whole seconds until the next refresh (never negative)."""
    return max(0, round(_next_due - time.monotonic()))


def _publish() -> None:
    companion.set_custom_variable(PROGRESS_VAR, str(remaining()))


def start(interval: float = FEEDBACK_INTERVAL) -> None:
    """Start the once-a-second countdown ticker (daemon thread)."""
    mark(interval)

    def loop():
        while True:
            try:
                _publish()
            except Exception as e:  # noqa: BLE001 - an OSC hiccup must not kill the tick
                log.warning("progress publish failed: %s", e)
            time.sleep(PROGRESS_TICK)

    threading.Thread(target=loop, name="progress", daemon=True).start()
