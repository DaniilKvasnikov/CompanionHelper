"""Menu tree node types and filename conventions.

Filename conventions (the prefix `NN_` only controls ordering + is stripped
from the display label):

    01_lights/            -> submenu (folder)
    01_on.py              -> command button
    01_cpu.fb.py          -> feedback button (polled + refreshed on entry)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Extensions we know how to run. See runner.RUNNERS for the actual commands.
SCRIPT_EXTS = {".py", ".sh", ".ps1", ".bat", ".cmd", ".exe", ""}


@dataclass
class MenuNode:
    """A submenu (directory). `children` are ordered by filename."""
    name: str
    path: Path
    label: str
    children: list = field(default_factory=list)


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
