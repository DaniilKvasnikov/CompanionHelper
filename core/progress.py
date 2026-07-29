"""Progress toward the next auto-refresh, published as a Companion custom variable.

A button that shows `$(custom:Progress)` gets a 0..100 value: 0 right after a
feedback refresh, filling to 100 as the next one approaches (a progress-bar
percentage, not a seconds countdown). A daemon thread ticks once a second; the
feedback poller calls `mark()` at the end of each cycle so the value stays in
sync with the real refresh cadence (rather than free-running and drifting).

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


def percent() -> int:
    """How far we are toward the next refresh, 0..100 (0 = just refreshed)."""
    if _interval <= 0:
        return 100
    elapsed = _interval - (_next_due - time.monotonic())
    return max(0, min(100, round(elapsed / _interval * 100)))


def _publish() -> None:
    companion.set_custom_variable(PROGRESS_VAR, str(percent()))


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
