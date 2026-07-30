"""FreeFileSync sync jobs, as a dynamic main-menu tab.

A "Sync" tab lists the FreeFileSync batch jobs configured in FFS_JOBS
(core/config.py) as (label, path-to-.ffs_batch) pairs. Pressing a button runs

    FreeFileSync.exe <batch>

and shows the result on the button. Fail-soft: a missing exe, a timeout, or a
non-zero exit becomes button text, never a crash. This tab is stateless — it
reads FFS_JOBS from config, so there is no disk catalog and nothing to refresh.
See CLAUDE.md for the conventions.
"""
from __future__ import annotations

import logging
import subprocess

from .config import FFS_EXE, FFS_JOBS, FFS_TIMEOUT
from .constants import After, Kind
from .model import ActionNode, MenuNode

log = logging.getLogger("ffs")


def _run_job(path: str) -> str:
    """Run one FreeFileSync batch; return a short OK / ERR line for the button."""
    try:
        proc = subprocess.run(
            [FFS_EXE, path], capture_output=True, text=True, timeout=FFS_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001 - exe missing/timeout must not crash the deck
        log.warning("FreeFileSync failed for %s: %s", path, e)
        return f"ERR\n{e}"[:60]
    if proc.returncode == 0:
        return "OK"
    lines = (proc.stderr or proc.stdout or "").strip().splitlines()
    detail = lines[-1] if lines else f"code {proc.returncode}"
    log.warning("FreeFileSync %s exited %s", path, proc.returncode)
    return f"ERR\n{detail}"[:60]


# --- menu tree ------------------------------------------------------------
def attach(root: MenuNode) -> None:
    """Insert the Sync (FreeFileSync) tab at the end of the main menu."""
    root.children.append(
        MenuNode(name="__ffs__", path=None, label="Sync", provider=_ffs_children)
    )


def _ffs_children(node) -> list:
    return [
        ActionNode(
            name=label, label=label, kind=Kind.COMMAND, after=After.TEXT,
            on_press=lambda p=path: _run_job(p),
        )
        for label, path in FFS_JOBS
    ]
