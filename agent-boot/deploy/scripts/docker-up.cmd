@echo off
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0docker-up.ps1" %*
exit /b %ERRORLEVEL%
