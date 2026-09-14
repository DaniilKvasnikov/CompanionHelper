"""Diagnostics: WHY a reader got no data (a small, deduplicated ring of problems).

The status page is a monitor, and "ERR" / a grey dot never says what actually
went wrong: was the controller unreachable, did it answer 404, did it answer
something without the expected field, is the group file empty, is the PDQ
database missing? Every reader records the REASON here
(core/aoto, core/pixelhue, core/pcbrowser, core/webstatus), and the page serves
it as a separate log window (GET /logs).

Semantics:
  * an entry is a CURRENT problem, keyed by (source, target, message) -- the
    target is usually the exact URL that was tried, so the log answers "why";
  * repeats are folded into one row: a `count` plus first/last seen time, so a
    controller that has been down for an hour is ONE line, not 1800;
  * `resolved(source, target)` drops the rows of a target as soon as a read of
    it succeeds, so the log shows what is broken NOW;
  * the ring keeps at most DIAG_MAX problems -- the oldest is dropped.

One module, one job: this is a bucket with a lock. It never does I/O, and it is
cheap enough to call from a poll loop (a dict lookup in the common case).
"""
from __future__ import annotations

import logging
import threading
import time

from .config import DIAG_MAX

log = logging.getLogger("diag")

_lock = threading.RLock()
_items: dict[tuple[str, str, str], dict] = {}   # key -> entry (insertion = oldest first)


def record(source: str, target: str, message: str) -> None:
    """Note that `source` could not read `target`, and why.

    Called on every failed attempt: an identical problem only bumps its counter
    and its `last` timestamp."""
    key = (source, str(target), str(message))
    now = time.strftime("%H:%M:%S")
    with _lock:
        entry = _items.pop(key, None)          # pop+insert = most recent goes last
        if entry is None:
            entry = {"source": source, "target": str(target), "message": str(message),
                     "count": 0, "first": now, "last": now}
            log.info("problem: %s %s -- %s", source, target, message)
            while len(_items) >= DIAG_MAX:      # drop the oldest problem
                _items.pop(next(iter(_items)))
        entry["count"] += 1
        entry["last"] = now
        _items[key] = entry


def resolved(source: str, target: str) -> None:
    """A read of `target` succeeded: its problems are fixed, drop them."""
    target = str(target)
    with _lock:
        for key in [k for k in _items if k[0] == source and k[1] == target]:
            del _items[key]


def entries() -> list[dict]:
    """Current problems, most recently seen first."""
    with _lock:
        return [dict(e) for e in reversed(_items.values())]


def problems() -> int:
    """How many distinct problems are open (the page's badge)."""
    with _lock:
        return len(_items)


def clear() -> None:
    """Forget every problem (tests, and a manual reset)."""
    with _lock:
        _items.clear()
