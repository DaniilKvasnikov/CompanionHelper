"""develop: the pull-and-restart and open-status-page buttons.

git and the process restart are faked by monkeypatching develop._git_pull and
develop._schedule_restart, and the browser by monkeypatching
develop.webbrowser.open, so no real subprocess runs, the test process is never
replaced and no browser window opens.
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


def test_develop_children_has_pull_restart_and_status_page():
    kids = develop._develop_children(None)
    assert [k.name for k in kids] == ["pull-restart", "status-page"]
    assert all(isinstance(k, ActionNode) for k in kids)
    assert all(k.after == After.TEXT and k.kind == Kind.COMMAND for k in kids)
    assert kids[0].on_press is develop.pull_and_restart
    assert kids[1].on_press is develop.open_status_page


def test_open_status_page_opens_the_page_url(monkeypatch):
    opened = []
    monkeypatch.setattr(develop.webbrowser, "open", lambda url: opened.append(url) or True)
    assert develop.open_status_page() == "OK"
    assert opened == [develop.webstatus.page_url()]
    assert opened[0].startswith("http://127.0.0.1:") and opened[0].endswith("/")


def test_open_status_page_reports_a_missing_browser(monkeypatch):
    monkeypatch.setattr(develop.webbrowser, "open", lambda url: False)
    assert develop.open_status_page().startswith("ERR")


def test_open_status_page_fails_soft(monkeypatch):
    def boom(url):
        raise RuntimeError("no browser here")

    monkeypatch.setattr(develop.webbrowser, "open", boom)
    assert develop.open_status_page().startswith("ERR")
