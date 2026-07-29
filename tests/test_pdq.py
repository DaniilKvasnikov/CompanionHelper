"""PDQ arg building and .pdq config resolution (no DB / no CLI)."""
import json

import pytest

from core import pdq


def test_deploy_args():
    assert pdq.deploy_args("P", ["a", "b"]) == ["Deploy", "-Package", "P", "-Targets", "a", "b"]
    assert pdq.deploy_args("P", []) == ["Deploy", "-Package", "P"]


def test_schedule_args():
    assert pdq.schedule_args(7) == ["StartSchedule", "7"]


def test_args_from_config_specific_targets():
    args = pdq.args_from_config({"package": "P", "targets": ["x"]})
    assert args == ["Deploy", "-Package", "P", "-Targets", "x"]


def test_args_from_config_schedule():
    assert pdq.args_from_config({"schedule": 3}) == ["StartSchedule", "3"]


def test_args_from_config_target_list_expands_members(monkeypatch):
    monkeypatch.setattr(pdq, "target_list_members", lambda name: ["h1", "h2"])
    args = pdq.args_from_config({"package": "P", "target_list": "L"})
    assert args == ["Deploy", "-Package", "P", "-Targets", "h1", "h2"]


def test_args_from_config_empty_target_list_raises(monkeypatch):
    monkeypatch.setattr(pdq, "target_list_members", lambda name: [])
    with pytest.raises(ValueError):
        pdq.args_from_config({"package": "P", "target_list": "L"})


def test_args_from_config_needs_package_or_schedule():
    with pytest.raises(ValueError):
        pdq.args_from_config({"foo": 1})
    with pytest.raises(ValueError):
        pdq.args_from_config({"package": "P"})  # no targets / target_list


def test_run_config_reads_file_and_calls_cli(tmp_path, monkeypatch):
    captured = {}

    def fake_run(args, timeout=None):
        captured["args"] = args
        return (0, "started", "")

    monkeypatch.setattr(pdq, "run", fake_run)
    f = tmp_path / "x.pdq"
    f.write_text(json.dumps({"package": "P", "targets": ["h"]}))

    code, out, _ = pdq.run_config(f)
    assert captured["args"] == ["Deploy", "-Package", "P", "-Targets", "h"]
    assert code == 0 and out == "started"


def test_run_config_bad_json_fails_soft(tmp_path):
    f = tmp_path / "x.pdq"
    f.write_text("{not json")
    code, _, err = pdq.run_config(f)
    assert code == -1 and "bad .pdq" in err
