"""progress: the countdown math and the custom-variable publish."""
import pytest

from core import progress


@pytest.fixture
def clock(monkeypatch):
    """A controllable monotonic clock for deterministic countdown math."""
    t = {"now": 100.0}
    monkeypatch.setattr(progress.time, "monotonic", lambda: t["now"])
    return t


def test_mark_starts_at_zero_percent(clock):
    progress.mark(5.0)
    assert progress.percent() == 0


def test_percent_fills_toward_next_refresh(clock):
    progress.mark(5.0)          # due at 105
    clock["now"] = 102.5
    assert progress.percent() == 50    # halfway
    clock["now"] = 104.9
    assert progress.percent() == 98


def test_percent_clamped_at_100_when_overdue(clock):
    progress.mark(5.0)
    clock["now"] = 200.0        # long past due
    assert progress.percent() == 100


def test_mark_without_arg_reuses_last_interval(clock):
    progress.mark(8.0)          # remember 8s
    clock["now"] = 108.0        # a full interval elapsed
    progress.mark()             # reset, no explicit interval
    assert progress.percent() == 0     # reset -> 0%, still an 8s interval
    clock["now"] = 112.0
    assert progress.percent() == 50    # 4s of 8s


def test_publish_sets_progress_custom_variable(clock, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        progress.companion, "set_custom_variable",
        lambda name, value: captured.update(name=name, value=value),
    )
    progress.mark(5.0)
    clock["now"] = 102.5
    progress._publish()
    assert captured == {"name": progress.PROGRESS_VAR, "value": "50"}
