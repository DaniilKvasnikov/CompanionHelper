@echo off
REM Remove the CompanionHelper auto-start scheduled task.
REM Run as administrator on the target machine.
setlocal
set "TASK=CompanionHelper"
schtasks /Delete /TN "%TASK%" /F
endlocal
