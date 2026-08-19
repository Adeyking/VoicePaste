param(
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $PSScriptRoot "voicepaste.pid"
$metaFile = Join-Path $PSScriptRoot "voicepaste.process.json"
. (Join-Path $PSScriptRoot "common_config.ps1")

if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repoRoot "voicepaste.config.json"
}
$resolvedConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)

function Get-PidFromFile {
    if (-not (Test-Path $pidFile)) {
        return $null
    }

    $raw = (Get-Content -Path $pidFile -Raw).Trim()
    if (-not $raw) {
        return $null
    }

    $pidValue = 0
    if (-not [int]::TryParse($raw, [ref]$pidValue)) {
        return $null
    }

    return $pidValue
}

function Test-VoicePasteProcess {
    param([int]$PidValue)

    $proc = Get-Process -Id $PidValue -ErrorAction SilentlyContinue
    if (-not $proc) {
        return $null
    }

    $procInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $PidValue" -ErrorAction SilentlyContinue
    if (-not $procInfo) {
        return $null
    }

    $cmd = [string]$procInfo.CommandLine
    if (-not $cmd) {
        return $null
    }

    if ($cmd -notmatch "client\.py") {
        return $null
    }

    if ($cmd -notmatch "VoicePaste") {
        return $null
    }

    return [pscustomobject]@{
        Process = $proc
        CommandLine = $cmd
    }
}

function Find-ExistingTrayProcesses {
    $procInfos = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -eq "python.exe" -and
        $_.CommandLine -and
        $_.CommandLine -match "voicepaste\.tray_app"
    }

    if (-not $procInfos) {
        return @()
    }

    $procs = @()
    foreach ($procInfo in $procInfos) {
        $proc = Get-Process -Id $procInfo.ProcessId -ErrorAction SilentlyContinue
        if ($proc) {
            $procs += $proc
        }
    }
    return $procs
}

$existingPid = Get-PidFromFile
if ($existingPid) {
    $existing = Test-VoicePasteProcess -PidValue $existingPid
    if ($existing) {
        Write-Output "Voice Translator already running (PID $existingPid)"
        exit 0
    }
}

$runningTrays = @(Find-ExistingTrayProcesses)
if ($runningTrays.Count -gt 0) {
    $trayPids = ($runningTrays | Sort-Object Id | ForEach-Object { $_.Id }) -join ", "
    Write-Output "Voice Translator tray is already running (PID $trayPids). Stop tray before starting legacy CLI mode to avoid duplicate hotkeys."
    exit 0
}

if (Test-Path $pidFile) {
    Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
}
if (Test-Path $metaFile) {
    Remove-Item -Path $metaFile -Force -ErrorAction SilentlyContinue
}

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Output "Voice Translator failed to start: python not found"
    exit 1
}

if (-not (Test-Path $resolvedConfigPath)) {
    Write-Output "Voice Translator warning: config not found at $resolvedConfigPath (client defaults will apply)"
}

$resolved = Get-VoicePasteResolvedConfig -ConfigPath $resolvedConfigPath -RepoRoot $repoRoot -ApplyEnvOverrides
$healthUrl = Get-SttHealthUrl -SttUrl ([string]$resolved.STT_URL)
$sttOk = $false
try {
    $health = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 2
    $sttOk = ($health.status -eq "ok")
}
catch {
    $sttOk = $false
}

$args = @(".\client.py", "--config", $resolvedConfigPath)
$proc = Start-Process -FilePath $pythonCmd.Source -ArgumentList $args -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru

Set-Content -Path $pidFile -Value $proc.Id -Encoding ASCII
$meta = [pscustomobject]@{
    pid = $proc.Id
    started_at = (Get-Date).ToString("o")
    config_path = $resolvedConfigPath
    stt_health_url = $healthUrl
}
$meta | ConvertTo-Json | Set-Content -Path $metaFile -Encoding UTF8

if ($sttOk) {
    Write-Output "Voice Translator started (PID $($proc.Id)) | STT: reachable"
}
else {
    Write-Output "Voice Translator started (PID $($proc.Id)) | STT: unavailable (degraded mode)"
}
