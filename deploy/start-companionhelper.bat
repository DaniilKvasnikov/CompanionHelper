@echo off
REM Launches the CompanionHelper server. This wrapper is what the scheduled
REM task runs; it sets the working directory to the project root so relative
REM paths (menus\, aoto\, touch\, ...) resolve correctly.
REM
REM ADMIN GUARANTEE: PDQ deploys need an elevated (admin) token. The scheduled
REM task (deploy/install-autostart.bat) already runs this wrapper at HIGHEST,
REM so at logon the check below simply falls through. If this wrapper is ever
REM NOT elevated (started by hand without "Run as administrator", or a
REM misconfigured task), it relaunches ITSELF as administrator (one UAC
REM prompt) and exits - so the server always runs elevated.
REM Evidence is written to the log below ("Elevated: OK").
REM
REM Python resolution (machine-local, never needs an edit here -- so this file
REM stays shared and pull-safe across machines):
REM   1. a virtualenv INSIDE the project (project\.venv, git-ignored) if present;
REM   2. otherwise plain "python" from PATH.
REM Create your venv once per machine:  python -m venv .venv  in the project
REM root and install requirements into it. For any other layout, keep a local
REM copy of this file instead of editing it (edits here would conflict on pull).
setlocal

REM ---- evidence log (outside the repo) -----------------------------------
set "LOGDIR=%LOCALAPPDATA%\CompanionHelper"
if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>&1
set "LOG=%LOGDIR%\startup.log"
echo [%date% %time%] === CompanionHelper start === >> "%LOG%"

REM ---- elevation guard ----------------------------------------------------
REM S-1-16-12288 = "High Mandatory Level": present only in an elevated process.
whoami /groups 2>nul | findstr /C:"S-1-16-12288" >nul
if %errorlevel% equ 0 goto :elevated

echo [%date% %time%] NOT elevated - relaunching as administrator >> "%LOG%"
echo This server needs administrator rights for PDQ deploys.
echo Relaunching as administrator... confirm the UAC prompt.
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:elevated
echo [%date% %time%] Elevated: OK >> "%LOG%"

if exist "%~dp0..\.venv\Scripts\python.exe" (
    set "PYTHON=%~dp0..\.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)
cd /d "%~dp0.."
echo [%date% %time%] python: %PYTHON% ^| cwd: %CD% >> "%LOG%"
"%PYTHON%" main.py
