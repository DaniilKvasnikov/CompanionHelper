"""diag: the ring of open problems (dedupe, cap, resolve, order)."""
import re

import pytest

from core import diag


@pytest.fixture(autouse=True)
def empty_log(monkeypatch):
    monkeypatch.setattr(diag, "_items", {})
    return diag


def test_record_creates_one_entry(empty_log):
    diag.record("aoto", "http://10.0.0.1:8080/x", "timed out")
    entries = diag.entries()
    assert len(entries) == 1
    e = entries[0]
    assert (e["source"], e["target"], e["message"]) == ("aoto", "http://10.0.0.1:8080/x", "timed out")
    assert e["count"] == 1 and e["first"] == e["last"]
    assert re.fullmatch(r"\d\d:\d\d:\d\d", e["last"])       # wall clock, for the log window
    assert diag.problems() == 1


def test_repeats_are_folded_into_a_counter(empty_log):
    for _ in range(3):
        diag.record("aoto", "http://10.0.0.1:8080/x", "timed out")
    diag.record("aoto", "http://10.0.0.1:8080/x", "timed out")
    entries = diag.entries()
    assert len(entries) == 1 and entries[0]["count"] == 4
    assert diag.problems() == 1


def test_a_different_message_is_a_different_problem(empty_log):
    diag.record("aoto", "http://10.0.0.1:8080/x", "timed out")
    diag.record("aoto", "http://10.0.0.1:8080/x", "HTTP 404")
    assert diag.problems() == 2


def test_entries_are_newest_seen_first(empty_log):
    diag.record("aoto", "one", "boom")
    diag.record("aoto", "two", "boom")
    diag.record("aoto", "one", "boom")                      # seen again -> back to the top
    assert [e["target"] for e in diag.entries()] == ["one", "two"]


def test_resolved_drops_only_that_target(empty_log):
    diag.record("aoto", "one", "boom")
    diag.record("aoto", "two", "boom")
    diag.record("pixelhue", "one", "boom")
    diag.resolved("aoto", "one")
    assert sorted((e["source"], e["target"]) for e in diag.entries()) == \
        [("aoto", "two"), ("pixelhue", "one")]


def test_resolved_of_an_unknown_target_is_harmless(empty_log):
    diag.record("aoto", "one", "boom")
    diag.resolved("aoto", "nothing-here")
    assert diag.problems() == 1


def test_the_ring_keeps_only_the_newest_problems(empty_log, monkeypatch, caplog):
    monkeypatch.setattr(diag, "DIAG_MAX", 3)
    for i in range(5):
        diag.record("aoto", f"t{i}", "boom")
    assert [e["target"] for e in diag.entries()] == ["t4", "t3", "t2"]   # oldest dropped


def test_clear_empties_the_log(empty_log):
    diag.record("aoto", "one", "boom")
    diag.clear()
    assert diag.entries() == [] and diag.problems() == 0


def test_entries_are_copies(empty_log):
    diag.record("aoto", "one", "boom")
    diag.entries()[0]["count"] = 999
    assert diag.entries()[0]["count"] == 1                  # callers cannot corrupt the ring
