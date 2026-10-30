@echo off
rem Example task (stop at the first failing step): harmless steps for tests
setlocal

echo step 1 || exit /b 1
echo step 2 || exit /b 1

exit /b 0
