@echo off
rem Double-click to install or update claude-profiles, then open setup or the manager.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
pause
