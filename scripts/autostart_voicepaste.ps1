# VoicePaste autostart: launches unified tray app and embedded Config API (:8766) silently.
# Delegates to run_tray.ps1 which has duplicate detection and single-instance enforcement.
# Runs the PowerShell delegate hidden so no console window appears on the desktop.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$trayScript = Join-Path $root 'scripts\run_tray.ps1'

# Remove any stale single-instance lock file
Remove-Item -Path "$env:TEMP\voicepaste*.lock" -Force -ErrorAction SilentlyContinue

# Launch via run_tray.ps1 (hidden, no console window) which handles duplicate detection and PID tracking
Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", $trayScript, "-ConfigPath", (Join-Path $root "voicepaste.config.json")) -WindowStyle Hidden
