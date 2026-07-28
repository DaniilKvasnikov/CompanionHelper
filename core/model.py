"""Menu tree node types and filename conventions.

Filename conventions (the prefix `NN_` only controls ordering + is stripped
from the display label):

    01_lights/            -> submenu (folder)
    01_on.py              -> command button
    01_cpu.fb.py          -> feedback button (polled + refreshed on entry)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Extensions we treat as buttons. `.pdq` is a JSON config for a PDQ Deploy
# action (handled in runner via core.pdq); the rest are executed directly.
# See runner.RUNNERS for the actual commands.
SCRIPT_EXTS = {".py", ".sh", ".ps1", ".bat", ".cmd", ".exe", ".pdq", ""}


@dataclass
class MenuNode:
    """A submenu. Static (`children` from disk) or dynamic (`provider`).

    A dynamic menu leaves `children` empty and sets `provider`, a callable that
    returns the children on demand (see `children_of`). `context` carries data
    down a dynamic branch (e.g. which PC this menu is for); `color_fn` gives the
    button a runtime color (e.g. ping status).
    """
    name: str
    path: Optional[Path]
    label: str
    children: list = field(default_factory=list)
    provider: Optional[Callable] = None
    context: dict = field(default_factory=dict)
    color_fn: Optional[Callable] = None


@dataclass
class CommandNode:
    """A button backed by an executable script file."""
    name: str
    path: Path
    label: str
    feedback: bool = False

    @property
    def key(self) -> str:
        """Stable identity for storing last-known feedback text."""
        return str(self.path)


@dataclass
class ActionNode:
    """A dynamic button that runs a Python callable instead of a file.

    `on_press` returns text to show on the button. `after` controls what
    happens next: 'text' (show the returned text), 'rerender' (redraw the page,
    e.g. content changed), or 'back' (pop up one level then redraw).
    """
    name: str
    label: str
    on_press: Callable[[], str]
    kind: str = "command"            # base color key in config.COLORS
    after: str = "text"              # 'text' | 'rerender' | 'back'
    color_fn: Optional[Callable] = None
    context: dict = field(default_factory=dict)


def children_of(node) -> list:
    """Children of a menu node: from its provider if dynamic, else static."""
    provider = getattr(node, "provider", None)
    if provider is None:
        return getattr(node, "children", [])
    try:
        return provider(node)
    except Exception as e:  # a DB hiccup must not crash rendering
        logging.getLogger("model").warning("provider for %r failed: %s", getattr(node, "name", "?"), e)
        return [ActionNode(name="__err__", label=f"ERR\n{e}", on_press=lambda: "")]


def is_script(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SCRIPT_EXTS


def is_feedback(path: Path) -> bool:
    # e.g. "01_cpu.fb.py" -> stem "01_cpu.fb"
    return path.stem.endswith(".fb")


def make_label(name: str, is_dir: bool) -> str:
    """Derive a human label: drop NN_ prefix, extensions and `.fb`, prettify."""
    base = name
    if not is_dir:
        p = Path(name)
        base = p.name[: -len(p.suffix)] if p.suffix else p.name
        if base.endswith(".fb"):
            base = base[:-3]
    base = re.sub(r"^\d+[_\-\s]*", "", base)                 # strip NN_ prefix
    base = base.replace("_", " ").replace("-", " ").strip()
    if not base:
        return name
    return " ".join(w.capitalize() for w in base.split())
