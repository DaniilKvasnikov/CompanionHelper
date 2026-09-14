"""PDQ Deploy integration.

Two halves, because PDQ Deploy 20.x splits them:
  - READ package / target-list names and the deployment journal from PDQ's
    SQLite database (the CLI has no command to enumerate them, and on-prem
    PDQ Deploy has no REST API -- only the cloud PDQ Connect does).
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
    python -m core.pdq deployments      # the journal: what ran, and how it ended

The deployment journal is the `Deployments` table (columns include
`DeploymentId`, `PackageName`, `Status` -- 'Running'/'Success'/'Failed'/...),
with one `DeploymentComputers` row per target. PDQ does not document the
schema and it differs between versions, so recent_deployments() reads whole
rows and webstatus picks the fields it understands; when a table or column is
missing the error says exactly which columns/tables DO exist, so the log window
answers "почему пусто" instead of leaving it a mystery.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from .config import PDQ_DB_PATH, PDQ_DEPLOY_EXE, PDQ_TIMEOUT

log = logging.getLogger("pdq")

# (exit code, stdout, stderr)
Result = tuple[int, str, str]


class PdqSchemaError(RuntimeError):
    """The PDQ database is there, but not the table/column we need.

    The message carries what was found instead (table or column names), because
    that is the only way to adapt from another machine without a debugger."""


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


# --- database reads: the deployment journal (what ran, how it ended) -------
def _table_names(con) -> list[str]:
    try:
        return [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    except sqlite3.Error:  # noqa: BLE001 - diagnostics only
        return []


def _column_names(con, table: str) -> list[str]:
    try:
        return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    except sqlite3.Error:  # noqa: BLE001 - diagnostics only
        return []


def recent_deployments(limit: int = 8, with_targets: bool = True) -> list[dict]:
    """The newest rows of PDQ's `Deployments` table, newest first.

    Every column of the row is kept (the schema is undocumented and varies), and
    with `with_targets` each row also gets `targets` -- the `DeploymentComputers`
    rows, i.e. where that deployment went and how each machine ended up. One
    snapshot copy of the DB serves the whole call.

    Raises PdqSchemaError (with the tables/columns that DO exist) when the
    journal is not where we expect it, and sqlite3.Error when the DB itself
    cannot be read (e.g. PDQ is not installed on this machine).
    """
    with _connect() as con:
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT * FROM Deployments ORDER BY DeploymentId DESC LIMIT ?", (int(limit),)
            ).fetchall()
        except sqlite3.Error as e:
            # Older/newer builds may not have DeploymentId: fall back to rowid.
            try:
                rows = con.execute(
                    "SELECT * FROM Deployments ORDER BY rowid DESC LIMIT ?", (int(limit),)
                ).fetchall()
            except sqlite3.Error:
                raise PdqSchemaError(
                    f"таблица Deployments не читается ({e}); "
                    f"колонки: {', '.join(_column_names(con, 'Deployments')) or '—'}; "
                    f"таблицы: {', '.join(_table_names(con)[:25]) or '—'}"
                ) from None
        out: list[dict] = []
        for row in rows:
            item = dict(row)
            if with_targets and item.get("DeploymentId") is not None:
                try:
                    item["targets"] = [dict(t) for t in con.execute(
                        "SELECT * FROM DeploymentComputers WHERE DeploymentId = ?",
                        (item["DeploymentId"],))]
                except sqlite3.Error as e:  # a journal without target rows is still useful
                    log.warning("DeploymentComputers unreadable: %s", e)
                    item["targets"] = []
            out.append(item)
        return out


# --- CLI deploy -----------------------------------------------------------
def deploy_args(package: str, targets: list[str]) -> list[str]:
    # PDQDeploy.exe wants the targets space-separated (each its own argv token),
    # not comma-joined: `-Targets PC1 PC2 ...`.
    args = ["Deploy", "-Package", package]
    if targets:
        args += ["-Targets", *targets]
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
    elif cmd in ("deployments", "journal"):
        for row in recent_deployments(limit=int(sys.argv[2]) if len(sys.argv) > 2 else 8):
            targets = row.get("targets") or []
            print(f"#{row.get('DeploymentId')}  {row.get('PackageName')}  "
                  f"{row.get('Status')}  ({len(targets)} ПК)")
            print("   колонки:", ", ".join(k for k in row if k != "targets"))
    else:
        print('usage: python -m core.pdq '
              '[packages | lists | members "<list name>" | deployments [N]]')
