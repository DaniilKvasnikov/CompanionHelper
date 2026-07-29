"""progress: the countdown math and the custom-variable publish."""
import pytest

from core import progress


@pytest.fixture
def clock(monkeypatch):
    """A controllable monotonic clock for deterministic countdown math."""
    t = {"now": 100.0}
    monkeypatch.setattr(progress.time, "monotonic", lambda: t["now"])
    return t


def test_mark_sets_countdown_to_interval(clock):
    progress.mark(5.0)
    assert progress.remaining() == 5


def test_remaining_counts_down(clock):
    progress.mark(5.0)          # due at 105
    clock["now"] = 102.4
    assert progress.remaining() == 3   # round(2.6)
    clock["now"] = 104.9
    assert progress.remaining() == 0   # round(0.1)


def test_remaining_clamped_at_zero_when_overdue(clock):
    progress.mark(5.0)
    clock["now"] = 200.0        # long past due
    assert progress.remaining() == 0


def test_mark_without_arg_reuses_last_interval(clock):
    progress.mark(8.0)          # remember 8s
    clock["now"] = 108.0        # elapsed
    progress.mark()             # reset, no explicit interval
    assert progress.remaining() == 8


def test_publish_sets_progress_custom_variable(clock, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        progress.companion, "set_custom_variable",
        lambda name, value: captured.update(name=name, value=value),
    )
    progress.mark(5.0)
    progress._publish()
    assert captured == {"name": progress.PROGRESS_VAR, "value": "5"}
