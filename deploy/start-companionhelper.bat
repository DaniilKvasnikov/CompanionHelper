@echo off
REM Launches the CompanionHelper server. This wrapper is what the scheduled
REM task runs; it sets the working directory to the project root so relative
REM paths (menus\, aoto\, touch\, ...) resolve correctly.
REM
REM Python resolution (machine-local, never needs an edit here -- so this file
REM stays shared and pull-safe across machines):
REM   1. a virtualenv INSIDE the project (project\.venv, git-ignored) if present;
REM   2. otherwise plain "python" from PATH.
REM Create your venv once per machine:  python -m venv .venv  in the project
REM root and install requirements into it. For any other layout, keep a local
REM copy of this file instead of editing it (edits here would conflict on pull).
setlocal
if exist "%~dp0..\.venv\Scripts\python.exe" (
    set "PYTHON=%~dp0..\.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)
cd /d "%~dp0.."
"%PYTHON%" main.py
