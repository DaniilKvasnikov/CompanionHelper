"""config: machine-local overrides from the git-ignored config.local.json.

The loader helpers are pure and unit-tested directly; the import-time
end-to-end behaviour (a JSON next to the package actually replacing the
defaults) is verified in a throwaway subprocess so no live repo state or
already-imported modules are touched.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from core import config
from core.constants import Kind

_PKG = Path(__file__).resolve().parent.parent / "core"


def _mini_repo(tmp_path: Path) -> Path:
    """A self-contained core/ package + project root so config imports cleanly."""
    root = tmp_path / "repo"
    dst = root / "core"
    dst.mkdir(parents=True)
    for name in ("__init__.py", "config.py", "constants.py"):
        shutil.copy2(_PKG / name, dst / name)
    return root


# --- reading the local file ------------------------------------------------
def test_read_local_config_missing_file_is_empty(tmp_path):
    assert config._read_local_config(tmp_path / "nope.json") == {}


def test_read_local_config_valid_object_drops_notes(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"_note": "hi", "DEFAULT_PAGE": "7", "FFS_JOBS": []}),
                 encoding="utf-8")
    assert config._read_local_config(p) == {"DEFAULT_PAGE": "7", "FFS_JOBS": []}


def test_read_local_config_bad_json_is_empty(tmp_path, caplog):
    p = tmp_path / "c.json"
    p.write_text("{not json", encoding="utf-8")
    assert config._read_local_config(p) == {}
    assert "not valid JSON" in caplog.text


def test_read_local_config_non_object_is_empty(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("[1, 2]", encoding="utf-8")
    assert config._read_local_config(p) == {}


# --- applying overrides ----------------------------------------------------
def test_apply_local_overrides_replaces_known_names():
    target = {"FFS_JOBS": [("a", "x")], "PING_TIMEOUT_MS": 800, "Kind": Kind}
    applied = config.apply_local_overrides(
        {"FFS_JOBS": [["b", "y"]], "PING_TIMEOUT_MS": 123}, into=target)
    assert applied == ["FFS_JOBS", "PING_TIMEOUT_MS"]
    assert target["FFS_JOBS"] == [["b", "y"]]
    assert target["PING_TIMEOUT_MS"] == 123
    assert target["Kind"] is Kind          # untouched (not in overrides)


def test_apply_local_overrides_ignores_unknown_and_non_data_names(caplog):
    target = {"DEFAULT_PAGE": "1"}
    applied = config.apply_local_overrides(
        {"DEFAULT_PAGE": "9", "Bogus": 1, "Kind": "menu"}, into=target)
    assert applied == ["DEFAULT_PAGE"]
    assert target["DEFAULT_PAGE"] == "9"
    assert "Bogus" in caplog.text and "Kind" in caplog.text   # both warned


def test_overridable_names_are_uppercase_data_constants():
    assert "DEFAULT_PAGE" in config._OVERRIDABLE
    assert "FFS_JOBS" in config._OVERRIDABLE
    assert "Kind" not in config._OVERRIDABLE          # an imported class
    assert not any(n.startswith("_") for n in config._OVERRIDABLE)


# --- end-to-end: the file really overrides at import time ------------------
def test_local_json_overrides_defaults_on_import(tmp_path):
    root = _mini_repo(tmp_path)
    (root / "config.local.json").write_text(
        json.dumps({"DEFAULT_PAGE": "9", "OSC_PORT": 9999,
                    "FFS_JOBS": [["Photos", "D:/sync/photo.ffs_batch"]]}),
        encoding="utf-8")
    code = ("import core.config as c\n"
            "print(c.DEFAULT_PAGE)\nprint(c.OSC_PORT)\nprint(repr(c.FFS_JOBS))")
    out = subprocess.run([sys.executable, "-c", code], cwd=root,
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines() == ["9", "9999", "[['Photos', 'D:/sync/photo.ffs_batch']]"]


def test_local_json_unknown_key_is_ignored_not_fatal(tmp_path):
    root = _mini_repo(tmp_path)
    (root / "config.local.json").write_text(
        json.dumps({"DEFAULT_PAGE": "9", "Bogus_Key": 1}), encoding="utf-8")
    code = "import core.config as c\nprint(c.DEFAULT_PAGE)\nprint(c.OSC_PORT)"
    out = subprocess.run([sys.executable, "-c", code], cwd=root,
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0
    assert out.stdout.splitlines() == ["9", str(config.OSC_PORT)]  # bogus key skipped


def test_local_json_invalid_is_harmless(tmp_path):
    root = _mini_repo(tmp_path)
    (root / "config.local.json").write_text("{oops", encoding="utf-8")
    code = "import core.config as c\nprint(c.DEFAULT_PAGE)"
    out = subprocess.run([sys.executable, "-c", code], cwd=root,
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0
    assert out.stdout.splitlines() == [config.DEFAULT_PAGE]        # defaults kept
