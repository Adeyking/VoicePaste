param(
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "SilentlyContinue"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $PSScriptRoot "voicepaste.pid"
$metaFile = Join-Path $PSScriptRoot "voicepaste.process.json"
$trayPidFile = Join-Path $PSScriptRoot "voicepaste.tray.pid"
$trayMetaFile = Join-Path $PSScriptRoot "voicepaste.tray.process.json"
. (Join-Path $PSScriptRoot "common_config.ps1")
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repoRoot "voicepaste.config.json"
}

Write-Output "Voice Translator Diagnose"
Write-Output "==================="
Write-Output "Time: $(Get-Date -Format o)"
Write-Output "Repo: $repoRoot"
Write-Output "Config: $ConfigPath"
Write-Output ""

$resolved = Get-VoicePasteResolvedConfig -ConfigPath $ConfigPath -RepoRoot $repoRoot -ApplyEnvOverrides
$sttUrl = [string]$resolved.STT_URL
$ollamaUrl = [string]$resolved.OLLAMA_URL
$logDir = [Environment]::ExpandEnvironmentVariables([string]$resolved.LOG_DIR)
$sttHealthUrl = Get-SttHealthUrl -SttUrl $sttUrl
$ollamaVersionUrl = $ollamaUrl.TrimEnd("/") + "/api/version"

Write-Output "Configured endpoints:"
Write-Output "  STT_URL:        $sttUrl"
Write-Output "  STT_HEALTH_URL: $sttHealthUrl"
Write-Output "  OLLAMA_URL:     $ollamaUrl"
Write-Output ""

function Get-PidFromMetaOrFile {
    param(
        [string]$MetaPath,
        [string]$PidPath
    )

    if (Test-Path $MetaPath) {
        try {
            $meta = Get-Content -Path $MetaPath -Raw | ConvertFrom-Json
            if ($meta.pid) { return [int]$meta.pid }
        }
        catch {
        }
    }

    if (Test-Path $PidPath) {
        $raw = (Get-Content -Path $PidPath -Raw).Trim()
        $tmp = 0
        if ([int]::TryParse($raw, [ref]$tmp)) { return $tmp }
    }

    return $null
}

$cliPid = Get-PidFromMetaOrFile -MetaPath $metaFile -PidPath $pidFile
$trayPid = Get-PidFromMetaOrFile -MetaPath $trayMetaFile -PidPath $trayPidFile

$runningProc = $null
$procKind = ""

if ($trayPid) {
    $proc = Get-Process -Id $trayPid -ErrorAction SilentlyContinue
    if ($proc) {
        $runningProc = $proc
        $procKind = "tray"
    }
}

if (-not $runningProc -and $cliPid) {
    $proc = Get-Process -Id $cliPid -ErrorAction SilentlyContinue
    if ($proc) {
        $runningProc = $proc
        $procKind = "cli"
    }
}

if (-not $runningProc) {
    $scan = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -eq "python.exe" -and
        $_.CommandLine -and
        (($_.CommandLine -match "client\.py") -or ($_.CommandLine -match "voicepaste\.tray_app"))
    } | Select-Object -First 1
    if ($scan) {
        $runningProc = Get-Process -Id $scan.ProcessId -ErrorAction SilentlyContinue
        $procKind = if ($scan.CommandLine -match "voicepaste\.tray_app") { "tray" } else { "cli" }
    }
}

Write-Output "Process status:"
if ($runningProc) {
    Write-Output "  Running: yes (PID $($runningProc.Id), mode=$procKind)"
    $procInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($runningProc.Id)" -ErrorAction SilentlyContinue
    if ($procInfo -and $procInfo.CommandLine) {
        Write-Output "  Command: $($procInfo.CommandLine)"
    }
} else {
    Write-Output "  Running: no"
}
Write-Output ""

Write-Output "Connectivity:"
try {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $resp = Invoke-RestMethod -Uri $sttHealthUrl -Method Get -TimeoutSec 3
    $sw.Stop()
    Write-Output "  STT health: ok ($($sw.ElapsedMilliseconds) ms) status=$($resp.status)"
}
catch {
    Write-Output "  STT health: fail ($_)"
}

try {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $resp = Invoke-RestMethod -Uri $ollamaVersionUrl -Method Get -TimeoutSec 3
    $sw.Stop()
    Write-Output "  Ollama version: ok ($($sw.ElapsedMilliseconds) ms) version=$($resp.version)"
}
catch {
    Write-Output "  Ollama version: fail ($_)"
}

Write-Output ""
if (Test-Path $logDir) {
    $latestLog = Get-ChildItem -Path $logDir -Filter "*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latestLog) {
        Write-Output "Last log file: $($latestLog.FullName)"
        Write-Output "---- tail (last 25 lines) ----"
        Get-Content -Path $latestLog.FullName -Tail 25
    }
    else {
        Write-Output "No log files found in $logDir"
    }
}
else {
    Write-Output "No log directory found ($logDir)"
}
