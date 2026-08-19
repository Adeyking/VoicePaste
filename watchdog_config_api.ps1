# VoicePaste Config API Watchdog
# Keeps voicepaste_config_api.py running. Auto-restarts within 5 seconds if it exits.
# Registered as a Task Scheduler task (AtLogon) — runs silently in the background.

$root = $PSScriptRoot
if (-not $root) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path }
$python = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) { $python = "pythonw.exe" }
$script = Join-Path $root "voicepaste_config_api.py"
$logFile = Join-Path $root "logs\config_api_watchdog.log"

function Write-Log($msg) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    "$ts  $msg" | Add-Content -Path $logFile -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null
Write-Log "Watchdog started"

while ($true) {
    # Check if port 8766 is already bound
    $conn = Get-NetTCPConnection -LocalPort 8766 -ErrorAction SilentlyContinue
    if ($conn) {
        # Already running — check again in 30s
        Start-Sleep -Seconds 30
        continue
    }

    Write-Log "Starting voicepaste_config_api.py ..."
    $proc = Start-Process -FilePath $python -ArgumentList $script -PassThru -WindowStyle Hidden
    Write-Log "Started PID $($proc.Id)"

    # Wait for the process to exit
    $proc.WaitForExit()
    Write-Log "Process exited (code $($proc.ExitCode)) — restarting in 5s"
    Start-Sleep -Seconds 5
}
