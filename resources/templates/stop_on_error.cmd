@echo off
rem Helper system task: stop at the first failing step
rem File name: <task id>.cmd / ASCII or ANSI / CRLF line endings
setlocal

powercfg /setactive SCHEME_MIN || exit /b 1
powercfg /hibernate off || exit /b 1

exit /b 0
