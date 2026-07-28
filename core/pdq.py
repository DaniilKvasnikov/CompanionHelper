"""PDQ Deploy integration.

Two halves, because PDQ Deploy 20.x splits them:
  - READ package / target-list names from PDQ's SQLite database (the CLI has
    no command to enumerate them).
  - DEPLOY via the CLI (PDQDeploy.exe), which needs Enterprise + admin + the
    background service. There is no `-TargetList` option, so to deploy to a
    Target List we expand its members from the DB into `-Targets`.

`.pdq` button config (JSON):
    {"package": "Install", "targets": ["PC1","PC2"]}   -> Deploy to those PCs
    {"package": "Install", "target_list": "Wall"}       -> expand list from DB
    {"schedule": 12}                                     -> StartSchedule

Discover what exists:
    python -m core.pdq packages
    python -m core.pdq lists
    python -m core.pdq members "Wall"
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from .config import PDQ_DB_PATH, PDQ_DEPLOY_EXE, PDQ_TIMEOUT

# (exit code, stdout, stderr)
Result = tuple[int, str, str]


# --- database reads (packages, target lists) ------------------------------
@contextlib.contextmanager
def _connect():
    """Yield a connection to a private snapshot of the live PDQ DB.

    Reading the live WAL database read-only misses data still in the -wal file
    (a Windows read-only-WAL limitation). So copy Database.db + -wal + -shm to
    a temp dir and open the copy, which applies the WAL and gives a consistent
    snapshot without ever touching (or locking) the running database.
    """
    tmpdir = tempfile.mkdtemp(prefix="pdqdb-")
    dst = os.path.join(tmpdir, "Database.db")
    try:
        for suffix in ("", "-wal", "-shm"):
            src = PDQ_DB_PATH + suffix
            if os.path.exists(src):
                shutil.copy2(src, dst + suffix)
        con = sqlite3.connect(dst)
        try:
            yield con
        finally:
            con.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def list_packages() -> list[str]:
    with _connect() as con:
        return [r[0] for r in con.execute("SELECT Name FROM Packages ORDER BY Name")]


def list_target_lists() -> list[str]:
    with _connect() as con:
        return [r[0] for r in con.execute("SELECT Name FROM TargetLists ORDER BY Name")]


def target_list_members(name: str) -> list[str]:
    query = """
        SELECT t.Name
        FROM TargetLists tl
        JOIN TargetListTargets m ON m.TargetListId = tl.TargetListId
        JOIN Targets t ON t.TargetId = m.TargetId
        WHERE tl.Name = ?
        ORDER BY t.Name
    """
    with _connect() as con:
        return [r[0] for r in con.execute(query, (name,))]


# --- CLI deploy -----------------------------------------------------------
def deploy_args(package: str, targets: list[str]) -> list[str]:
    args = ["Deploy", "-Package", package]
    if targets:
        args += ["-Targets", ",".join(targets)]
    return args


def schedule_args(schedule_id) -> list[str]:
    return ["StartSchedule", str(schedule_id)]


def args_from_config(cfg: dict) -> list[str]:
    """Turn a `.pdq` config into PDQDeploy.exe args (may read the DB)."""
    if cfg.get("schedule") is not None:
        return schedule_args(cfg["schedule"])

    package = cfg.get("package")
    if not package:
        raise ValueError("`.pdq` needs a 'package' (with 'targets' or 'target_list') or a 'schedule'")

    if cfg.get("targets"):
        targets = list(cfg["targets"])
    elif cfg.get("target_list"):
        name = cfg["target_list"]
        targets = target_list_members(name)
        if not targets:
            raise ValueError(f"target list {name!r} not found or empty")
    else:
        raise ValueError("`.pdq` needs 'targets' or 'target_list'")

    return deploy_args(package, targets)


def run(args: list[str], timeout: float = PDQ_TIMEOUT) -> Result:
    try:
        proc = subprocess.run(
            [PDQ_DEPLOY_EXE, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return -1, "", f"PDQDeploy.exe not found at {PDQ_DEPLOY_EXE}"
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:  # noqa: BLE001 - surface anything as button text
        return -1, "", str(e)


def run_config(path: Path, timeout: float = PDQ_TIMEOUT) -> Result:
    """Read a `.pdq` JSON file and run the PDQ command it describes."""
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return -1, "", f"bad .pdq config: {e}"
    try:
        args = args_from_config(cfg)
    except (ValueError, sqlite3.Error) as e:
        return -1, "", str(e)
    return run(args, timeout)


if __name__ == "__main__":  # discovery helper (reads the DB)
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "packages":
        print("\n".join(list_packages()))
    elif cmd in ("lists", "target-lists", "targetlists"):
        for name in list_target_lists():
            print(f"{name}  ({len(target_list_members(name))} targets)")
    elif cmd == "members" and len(sys.argv) > 2:
        print("\n".join(target_list_members(sys.argv[2])))
    else:
        print('usage: python -m core.pdq [packages | lists | members "<list name>"]')
