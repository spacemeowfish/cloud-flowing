@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Smoke-Test.ps1" %*
exit /b %ERRORLEVEL%
