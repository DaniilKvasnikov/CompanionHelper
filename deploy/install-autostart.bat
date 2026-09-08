@echo off
REM Register CompanionHelper to start automatically, ELEVATED (as admin),
REM at logon, via the Windows Task Scheduler.
REM
REM Run this ONCE, as administrator, on the TARGET machine (the one with
REM Companion + PDQ installed). "Run as administrator" on this .bat, or run it
REM from an elevated prompt.
REM
REM The wrapper (start-companionhelper.bat) additionally re-checks elevation on
REM every start and relaunches itself as administrator if it is not elevated,
REM so the server always runs with an admin token even outside this task.
setlocal
set "TASK=CompanionHelper"
set "WRAP=%~dp0start-companionhelper.bat"

REM /SC ONLOGON  - trigger when a user logs on (same session as Companion)
REM /RL HIGHEST  - run with highest privileges, i.e. elevated, no UAC prompt
REM /F           - overwrite the task if it already exists
schtasks /Create /TN "%TASK%" /TR "cmd /c \"%WRAP%\"" /SC ONLOGON /RL HIGHEST /F

if %ERRORLEVEL% EQU 0 (
  echo.
  echo Registered scheduled task "%TASK%".
  echo It will start elevated at the next logon of this user.
  echo.
  echo Verify now - "Run Level" must say Highest:
  echo     schtasks /Query /TN "%TASK%" /V /FO LIST
  echo.
  echo Start it right now without logging off:
  echo     schtasks /Run /TN "%TASK%"
) else (
  echo.
  echo Failed to register the task -- run this file as administrator.
)
endlocal
