param(
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common_config.ps1")

if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repoRoot "voicepaste.config.json"
}
$resolvedConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)

if (-not (Test-Path $resolvedConfigPath)) {
    Write-Output "Config not found: $resolvedConfigPath"
    exit 1
}

$resolved = Get-VoicePasteResolvedConfig -ConfigPath $resolvedConfigPath -RepoRoot $repoRoot
$sttUrl = [string]$resolved.STT_URL
$sttHealth = Get-SttHealthUrl -SttUrl $sttUrl

$ollamaUrl = [string]$resolved.OLLAMA_URL
$ollamaTags = $ollamaUrl.TrimEnd("/") + "/api/tags"

$logDir = [Environment]::ExpandEnvironmentVariables([string]$resolved.LOG_DIR)

$cfg = Get-Content -Path $resolvedConfigPath -Raw | ConvertFrom-Json
$modelProfile = [string]$cfg.MODEL_PROFILE
if (-not $modelProfile) {
    $modelProfile = "fast"
}
$activeModel = if ($modelProfile -eq "quality") { [string]$cfg.QUALITY_MODEL } else { [string]$cfg.FAST_MODEL }
if (-not $activeModel) {
    $activeModel = [string]$cfg.CLEAN_MODEL_LOCAL
}

Write-Output "Voice Translator Health Report"
Write-Output "Config: $resolvedConfigPath"
Write-Output "Model profile: $modelProfile"
Write-Output "Active model: $activeModel"

try {
    $h = Invoke-RestMethod -Uri $sttHealth -Method Get -TimeoutSec 3
    Write-Output "STT health: $($h.status)"
}
catch {
    Write-Output "STT health: unreachable ($($_.Exception.Message))"
}

try {
    $tags = Invoke-RestMethod -Uri $ollamaTags -Method Get -TimeoutSec 3
    $count = 0
    if ($tags.models) { $count = $tags.models.Count }
    Write-Output "Ollama health: reachable (models=$count)"
}
catch {
    Write-Output "Ollama health: unreachable ($($_.Exception.Message))"
}

Write-Output ""
Write-Output "Last 20 log lines:"

if (Test-Path $logDir) {
    $latestLog = Get-ChildItem -Path $logDir -Filter "voicepaste-*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latestLog) {
        Get-Content -Path $latestLog.FullName -Tail 20
    }
    else {
        Write-Output "(no log files found)"
    }
}
else {
    Write-Output "(log directory not found: $logDir)"
}
