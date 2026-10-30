@echo off
rem Example task (run every step): harmless steps for tests
setlocal
set "FAILED=0"

echo step 1 || set "FAILED=1"
echo step 2 || set "FAILED=1"

exit /b %FAILED%
