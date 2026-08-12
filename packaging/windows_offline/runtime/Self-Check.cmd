@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Self-Check.ps1" %*
exit /b %ERRORLEVEL%
