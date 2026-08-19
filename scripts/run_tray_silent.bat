@echo off
cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\run_tray.ps1" -ConfigPath "voicepaste.config.json"
