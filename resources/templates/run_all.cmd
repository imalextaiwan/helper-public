@echo off
rem Helper system task: run every step, fail if any step failed
rem File name: <task id>.cmd / ASCII or ANSI / CRLF line endings
setlocal
set "FAILED=0"

powercfg /change monitor-timeout-ac 0 || set "FAILED=1"
powercfg /change standby-timeout-ac 0 || set "FAILED=1"

exit /b %FAILED%
