"""RunResult helpers — the shared button-summary formatting."""
from core.runner import RunResult


def test_first_line_takes_first_stdout_line():
    assert RunResult(0, "one\ntwo", "").first_line() == "one"
    assert RunResult(0, "  \n", "").first_line() == ""


def test_summary_prefers_first_output_line():
    assert RunResult(0, "hello\nrest", "err").summary() == "hello"


def test_summary_ok_when_no_output_and_success():
    assert RunResult(0, "", "").summary() == "OK"


def test_summary_surfaces_stderr_on_failure():
    assert RunResult(1, "", "boom").summary() == "boom"


def test_summary_falls_back_to_err_label():
    assert RunResult(1, "", "").summary() == "ERR"
