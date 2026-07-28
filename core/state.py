"""Per-Companion-page navigation state, guarded by a single re-entrant lock."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

lock = threading.RLock()


@dataclass
class PageState:
    path: list = field(default_factory=list)      # folder names from root to here
    page_index: int = 0                            # pagination within current menu
    pages: int = 1
    feedback_values: dict = field(default_factory=dict)  # node.key -> display text
    rendered: dict = field(default_factory=dict)         # (row,col) -> (text,bg,fg)


_states: dict[str, PageState] = {}


def get_state(page: str) -> PageState:
    with lock:
        return _states.setdefault(page, PageState())


def all_pages() -> list[str]:
    with lock:
        return list(_states.keys())
