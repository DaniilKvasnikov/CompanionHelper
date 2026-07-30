"""Develop tab: pull the latest project changes and restart the server.

A "Develop" main-menu tab with a single button that runs `git pull` in the
project root and, on success, restarts this process (os.execv) so the new code
takes effect. The pull result is shown on the button first; the restart is
scheduled a moment later (RESTART_DELAY) so the deck renders that text before
the process is replaced. Fail-soft: a failed pull becomes button text, never a
crash, and does not restart. See CLAUDE.md for the conventions.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading

from .config import GIT_PULL_TIMEOUT, PROJECT_ROOT, RESTART_DELAY
from .constants import After, Kind
from .model import ActionNode, MenuNode

log = logging.getLogger("develop")


def _git_pull() -> tuple[bool, str]:
    """Run `git pull` in the project root; return (ok, combined output)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "pull"],
            capture_output=True, text=True, timeout=GIT_PULL_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001 - git missing/timeout must not crash the deck
        log.warning("git pull failed: %s", e)
        return (False, str(e))
    return (proc.returncode == 0, (proc.stdout + proc.stderr).strip())


def _restart() -> None:
    """Replace this process with a fresh run of the same command."""
    log.info("restarting: %s %s", sys.executable, sys.argv)
    os.execv(sys.executable, [sys.executable, *sys.argv])


def _schedule_restart() -> None:
    threading.Timer(RESTART_DELAY, _restart).start()   # let the deck render the result first


def pull_and_restart() -> str:
    ok, out = _git_pull()
    if not ok:
        return f"ERR\n{out[:60]}"
    _schedule_restart()
    summary = "Up to date" if "up to date" in out.lower() else "Pulled"
    return f"{summary}\nrestart..."


# --- menu tree ------------------------------------------------------------
def attach(root: MenuNode) -> None:
    """Insert the Develop menu at the end of the main menu."""
    root.children.append(
        MenuNode(name="__develop__", path=None, label="Develop", provider=_develop_children)
    )


def _develop_children(node) -> list:
    return [
        ActionNode(
            name="pull-restart", label="Pull &\nRestart", kind=Kind.COMMAND,
            after=After.TEXT, on_press=pull_and_restart,
        )
    ]
