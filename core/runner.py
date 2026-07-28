"""Run button scripts. Interpreter is chosen by file extension."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# ext -> function(path) -> argv
RUNNERS = {
    ".py": lambda p: [sys.executable, str(p)],
    ".sh": lambda p: ["bash", str(p)],
    ".ps1": lambda p: ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(p)],
    ".bat": lambda p: ["cmd", "/c", str(p)],
    ".cmd": lambda p: ["cmd", "/c", str(p)],
}


@dataclass
class RunResult:
    code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    def first_line(self) -> str:
        out = self.stdout.strip()
        return out.splitlines()[0] if out else ""

    def summary(self) -> str:
        """One line to show on a button: first output line, else OK / stderr / ERR."""
        return self.first_line() or ("OK" if self.ok else (self.stderr.strip() or "ERR"))


def _argv(path: Path) -> list[str]:
    return RUNNERS.get(path.suffix.lower(), lambda p: [str(p)])(path)


def run_script(path: Path, timeout: float) -> RunResult:
    if path.suffix.lower() == ".pdq":
        from . import pdq  # local import to avoid a cycle at module load

        return RunResult(*pdq.run_config(path))  # uses PDQ_TIMEOUT, not the command timeout
    try:
        proc = subprocess.run(
            _argv(path),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(path.parent),
        )
        return RunResult(proc.returncode, proc.stdout or "", proc.stderr or "")
    except subprocess.TimeoutExpired:
        return RunResult(-1, "", "timeout")
    except Exception as e:  # missing interpreter, permission, etc.
        return RunResult(-1, "", str(e))
