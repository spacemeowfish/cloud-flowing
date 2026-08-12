@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Accept-Licenses.ps1" %*
exit /b %ERRORLEVEL%
