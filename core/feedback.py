"""Background poller that keeps feedback buttons of active menus fresh."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

log = logging.getLogger("feedback")


def start_poller(
    refresh_fn: Callable[[str], None],
    pages_fn: Callable[[], list],
    interval: float,
) -> None:
    """Every `interval` seconds, refresh feedback buttons on every active page."""

    def loop():
        while True:
            time.sleep(interval)
            for page in pages_fn():
                try:
                    refresh_fn(page)
                except Exception as e:  # never let the poller die
                    log.warning("feedback refresh for page %s failed: %s", page, e)

    threading.Thread(target=loop, name="feedback-poller", daemon=True).start()
