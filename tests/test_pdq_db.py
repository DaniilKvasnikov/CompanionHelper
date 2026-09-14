"""DB reads in core.pdq against a synthetic snapshot of the PDQ schema.

Builds a real SQLite file with just the tables/columns pdq.py touches, points
PDQ_DB_PATH at it, and exercises the snapshot-copy _connect path for real.
"""
import sqlite3

import pytest

from core import pdq


def _build_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE Packages (Name TEXT);
        CREATE TABLE TargetLists (TargetListId INTEGER, Name TEXT);
        CREATE TABLE Targets (TargetId INTEGER, Name TEXT);
        CREATE TABLE TargetListTargets (TargetListId INTEGER, TargetId INTEGER);
        CREATE TABLE Deployments (DeploymentId INTEGER PRIMARY KEY, PackageName TEXT,
                                  Status TEXT, StartTime INTEGER, EndTime INTEGER);
        CREATE TABLE DeploymentComputers (DeploymentComputerId INTEGER PRIMARY KEY,
                                          DeploymentId INTEGER, Name TEXT, Status TEXT);
        """
    )
    con.executemany("INSERT INTO Packages (Name) VALUES (?)", [("Chrome",), ("7-Zip",)])
    con.executemany(
        "INSERT INTO TargetLists (TargetListId, Name) VALUES (?, ?)",
        [(1, "Office"), (2, "Empty")],
    )
    con.executemany(
        "INSERT INTO Targets (TargetId, Name) VALUES (?, ?)",
        [(10, "PC-B"), (11, "PC-A"), (12, "PC-C")],
    )
    con.executemany(
        "INSERT INTO TargetListTargets (TargetListId, TargetId) VALUES (?, ?)",
        [(1, 10), (1, 11)],  # Office = PC-B, PC-A ; Empty has no members
    )
    con.executemany(
        "INSERT INTO Deployments (DeploymentId, PackageName, Status, StartTime, EndTime) "
        "VALUES (?, ?, ?, ?, ?)",
        [(1, "7-Zip", "Success", 1735000000, 1735000100),
         (2, "Chrome", "Failed", 1735001000, 1735001100),
         (3, "Install", "Running", 1735002000, None)],
    )
    con.executemany(
        "INSERT INTO DeploymentComputers (DeploymentComputerId, DeploymentId, Name, Status) "
        "VALUES (?, ?, ?, ?)",
        [(1, 1, "PC-A", "Success"), (2, 1, "PC-B", "Success"),
         (3, 2, "PC-C", "Failed"), (4, 3, "PC-A", "Running")],
    )
    con.commit()
    con.close()


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "Database.db")
    _build_db(path)
    monkeypatch.setattr(pdq, "PDQ_DB_PATH", path)
    return path


def test_list_packages_sorted(db):
    assert pdq.list_packages() == ["7-Zip", "Chrome"]


def test_list_target_lists_sorted(db):
    assert pdq.list_target_lists() == ["Empty", "Office"]


def test_target_list_members_joined_and_sorted(db):
    assert pdq.target_list_members("Office") == ["PC-A", "PC-B"]


def test_empty_or_unknown_list_has_no_members(db):
    assert pdq.target_list_members("Empty") == []
    assert pdq.target_list_members("Nope") == []


def test_connect_snapshots_and_reads_wal(tmp_path, monkeypatch):
    """A row sitting only in the -wal must be visible through the snapshot copy."""
    path = str(tmp_path / "Database.db")
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE Packages (Name TEXT)")
    con.execute("INSERT INTO Packages (Name) VALUES ('InWal')")
    con.commit()  # committed but, in WAL mode, still living in Database.db-wal
    monkeypatch.setattr(pdq, "PDQ_DB_PATH", path)

    assert pdq.list_packages() == ["InWal"]
    con.close()


def test_args_from_config_target_list_uses_real_db(db):
    args = pdq.args_from_config({"package": "Chrome", "target_list": "Office"})
    assert args == ["Deploy", "-Package", "Chrome", "-Targets", "PC-A", "PC-B"]


# --- the deployment journal (what ran, how it ended) ------------------------
def test_recent_deployments_newest_first_with_targets(db):
    rows = pdq.recent_deployments()
    assert [r["DeploymentId"] for r in rows] == [3, 2, 1]        # newest first
    assert rows[0]["PackageName"] == "Install" and rows[0]["Status"] == "Running"
    # every column of the row survives, plus where it went
    assert rows[0]["StartTime"] == 1735002000
    assert [(t["Name"], t["Status"]) for t in rows[2]["targets"]] == \
        [("PC-A", "Success"), ("PC-B", "Success")]


def test_recent_deployments_limit_and_targets_switch(db):
    assert [r["DeploymentId"] for r in pdq.recent_deployments(limit=2)] == [3, 2]
    assert all("targets" not in r for r in pdq.recent_deployments(with_targets=False))


def test_recent_deployments_explains_a_missing_table(tmp_path, monkeypatch):
    """A journal we cannot read must say WHAT is in the DB instead."""
    path = str(tmp_path / "other.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE SomethingElse (X TEXT)")
    con.commit()
    con.close()
    monkeypatch.setattr(pdq, "PDQ_DB_PATH", path)

    with pytest.raises(pdq.PdqSchemaError) as e:
        pdq.recent_deployments()
    assert "Deployments" in str(e.value)
    assert "SomethingElse" in str(e.value)          # the tables that DO exist


def test_recent_deployments_accepts_a_journal_without_deployment_id(tmp_path, monkeypatch):
    """Older builds may not have DeploymentId -- ordering falls back to rowid."""
    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE Deployments (PackageName TEXT, Status TEXT)")
    con.executemany("INSERT INTO Deployments VALUES (?, ?)",
                    [("A", "Success"), ("B", "Running")])
    con.commit()
    con.close()
    monkeypatch.setattr(pdq, "PDQ_DB_PATH", path)

    rows = pdq.recent_deployments()
    assert [r["PackageName"] for r in rows] == ["B", "A"]        # rowid DESC
    assert all("targets" not in r for r in rows)                 # nothing to join on
