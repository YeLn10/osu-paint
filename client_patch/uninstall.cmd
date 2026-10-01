@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage-patch.ps1" -Action Uninstall %*
pause
