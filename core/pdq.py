"""PDQ Deploy CLI wrapper (Enterprise, local machine, elevated).

Buttons of type `.pdq` carry a small JSON config describing what to run:

    {"package": "7-Zip", "targets": ["PC1", "PC2"]}   -> Deploy to specific PCs
    {"schedule": 12}                                   -> StartSchedule (Target List)

Discover names/ids to put in those configs:

    python -m core.pdq packages     # PDQDeploy.exe GetPackageNames
    python -m core.pdq schedules     # PDQDeploy.exe GetSchedules  (id + name)

The CLI can't enumerate or deploy directly to a Target List; deploy to a list
by pre-making a Schedule in PDQ and referencing it via {"schedule": <id>}.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import PDQ_DEPLOY_EXE, PDQ_TIMEOUT

# (exit code, stdout, stderr)
Result = tuple[int, str, str]


def deploy_args(package: str, targets: list[str]) -> list[str]:
    args = ["Deploy", "-Package", package]
    if targets:
        args += ["-Targets", ",".join(targets)]
    return args


def schedule_args(schedule_id) -> list[str]:
    return ["StartSchedule", str(schedule_id)]


def args_from_config(cfg: dict) -> list[str]:
    if cfg.get("schedule") is not None:
        return schedule_args(cfg["schedule"])
    if cfg.get("package"):
        return deploy_args(cfg["package"], cfg.get("targets") or [])
    raise ValueError("`.pdq` needs a 'package' (with optional 'targets') or a 'schedule'")


def run(args: list[str], timeout: float = PDQ_TIMEOUT) -> Result:
    try:
        proc = subprocess.run(
            [PDQ_DEPLOY_EXE, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return -1, "", f"PDQDeploy.exe not found at {PDQ_DEPLOY_EXE}"
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:  # noqa: BLE001 - surface anything as button text
        return -1, "", str(e)


def run_config(path: Path, timeout: float = PDQ_TIMEOUT) -> Result:
    """Read a `.pdq` JSON file and run the PDQ command it describes."""
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return -1, "", f"bad .pdq config: {e}"
    try:
        args = args_from_config(cfg)
    except ValueError as e:
        return -1, "", str(e)
    return run(args, timeout)


def list_packages(timeout: float = PDQ_TIMEOUT) -> list[str]:
    _, out, _ = run(["GetPackageNames"], timeout)
    return [line.strip() for line in out.splitlines() if line.strip()]


if __name__ == "__main__":  # discovery helper
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "packages":
        print(run(["GetPackageNames"])[1], end="")
    elif cmd == "schedules":
        print(run(["GetSchedules"])[1], end="")
    else:
        print("usage: python -m core.pdq [packages|schedules]")
