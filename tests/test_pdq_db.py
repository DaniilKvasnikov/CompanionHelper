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
