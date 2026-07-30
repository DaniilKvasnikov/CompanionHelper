"""develop: the pull-and-restart button.

git and the process restart are faked by monkeypatching develop._git_pull and
develop._schedule_restart, so no real subprocess runs and the test process is
never replaced.
"""
from core import develop
from core.constants import After, Kind
from core.model import ActionNode, MenuNode


def test_pull_and_restart_schedules_restart_on_success(monkeypatch):
    scheduled = []
    monkeypatch.setattr(develop, "_git_pull", lambda: (True, "Updated 1 file"))
    monkeypatch.setattr(develop, "_schedule_restart", lambda: scheduled.append(True))
    text = develop.pull_and_restart()
    assert scheduled == [True]
    assert text.startswith("Pulled")


def test_pull_and_restart_reports_up_to_date(monkeypatch):
    monkeypatch.setattr(develop, "_git_pull", lambda: (True, "Already up to date."))
    monkeypatch.setattr(develop, "_schedule_restart", lambda: None)
    assert develop.pull_and_restart().startswith("Up to date")


def test_pull_and_restart_does_not_restart_on_failure(monkeypatch):
    scheduled = []
    monkeypatch.setattr(develop, "_git_pull", lambda: (False, "fatal: not a git repo"))
    monkeypatch.setattr(develop, "_schedule_restart", lambda: scheduled.append(True))
    text = develop.pull_and_restart()
    assert scheduled == []                 # a failed pull never restarts
    assert text.startswith("ERR")


def test_attach_adds_develop_tab_at_end():
    root = MenuNode("", None, "", children=[MenuNode("other", None, "Other")])
    develop.attach(root)
    assert root.children[-1].name == "__develop__"


def test_develop_children_is_a_single_pull_restart_button():
    kids = develop._develop_children(None)
    assert len(kids) == 1
    btn = kids[0]
    assert isinstance(btn, ActionNode)
    assert btn.on_press is develop.pull_and_restart
    assert btn.after == After.TEXT and btn.kind == Kind.COMMAND
