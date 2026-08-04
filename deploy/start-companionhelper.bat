@echo off
REM Launches the CompanionHelper server. This wrapper is what the scheduled
REM task runs; it sets the working directory to the project root so relative
REM paths (menus\, aoto\, touch\, ...) resolve correctly.
REM
REM If you run from a virtualenv, point PYTHON at its python.exe below,
REM e.g.  set "PYTHON=%~dp0..\.venv\Scripts\python.exe"
setlocal
set "PYTHON=python"
cd /d "%~dp0.."
"%PYTHON%" main.py
