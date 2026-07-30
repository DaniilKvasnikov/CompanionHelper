"""ffs: the FreeFileSync "Sync" tab — job buttons and running a batch.

FreeFileSync.exe is faked by monkeypatching ffs.subprocess.run, so no real
process is spawned.
"""
import pytest

from core import ffs
from core.constants import After, Kind
from core.model import ActionNode, MenuNode


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


@pytest.fixture
def jobs(monkeypatch):
    monkeypatch.setattr(ffs, "FFS_JOBS", [("Фото", r"D:\s\photo.ffs_batch"),
                                          ("Доки", r"D:\s\docs.ffs_batch")])


# --- running a batch ------------------------------------------------------
def test_run_job_ok(monkeypatch):
    monkeypatch.setattr(ffs.subprocess, "run", lambda *a, **k: _Proc(returncode=0))
    assert ffs._run_job("x.ffs_batch") == "OK"


def test_run_job_reports_error_detail(monkeypatch):
    monkeypatch.setattr(ffs.subprocess, "run",
                        lambda *a, **k: _Proc(returncode=2, stderr="disk full"))
    out = ffs._run_job("x.ffs_batch")
    assert out.startswith("ERR") and "disk full" in out


def test_run_job_missing_exe_is_soft(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("no exe")
    monkeypatch.setattr(ffs.subprocess, "run", boom)
    assert ffs._run_job("x.ffs_batch").startswith("ERR")


def test_run_job_passes_exe_and_batch_path(monkeypatch):
    seen = {}

    def fake_run(argv, **k):
        seen["argv"] = argv
        return _Proc(0)

    monkeypatch.setattr(ffs, "FFS_EXE", r"C:\FFS\FreeFileSync.exe")
    monkeypatch.setattr(ffs.subprocess, "run", fake_run)
    ffs._run_job(r"D:\s\photo.ffs_batch")
    assert seen["argv"] == [r"C:\FFS\FreeFileSync.exe", r"D:\s\photo.ffs_batch"]


# --- menu tree ------------------------------------------------------------
def test_attach_adds_sync_tab_at_end():
    root = MenuNode("", None, "", children=[MenuNode("other", None, "Other")])
    ffs.attach(root)
    assert root.children[-1].name == "__ffs__"
    assert root.children[-1].label == "Sync"


def test_ffs_children_builds_one_button_per_job(jobs):
    kids = ffs._ffs_children(None)
    assert [k.name for k in kids] == ["Фото", "Доки"]
    assert all(isinstance(k, ActionNode) and k.after == After.TEXT and k.kind == Kind.COMMAND
               for k in kids)


def test_button_press_runs_its_own_batch(jobs, monkeypatch):
    ran = []
    monkeypatch.setattr(ffs, "_run_job", lambda p: ran.append(p) or "OK")
    kids = ffs._ffs_children(None)
    kids[1].on_press()                       # "Доки"
    assert ran == [r"D:\s\docs.ffs_batch"]   # its own path, not the first job's
