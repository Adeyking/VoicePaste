$ErrorActionPreference = "Stop"

$pidFile = Join-Path $PSScriptRoot "voicepaste.pid"
$metaFile = Join-Path $PSScriptRoot "voicepaste.process.json"
$trayPidFile = Join-Path $PSScriptRoot "voicepaste.tray.pid"
$trayMetaFile = Join-Path $PSScriptRoot "voicepaste.tray.process.json"

function Get-PidFromFiles {
    param(
        [string]$MetaPath,
        [string]$PidPath
    )

    if (Test-Path $MetaPath) {
        try {
            $meta = Get-Content -Path $MetaPath -Raw | ConvertFrom-Json
            if ($meta.pid) {
                return [int]$meta.pid
            }
        }
        catch {
        }
    }

    if (Test-Path $PidPath) {
        $raw = (Get-Content -Path $PidPath -Raw).Trim()
        if ($raw) {
            $pidValue = 0
            if ([int]::TryParse($raw, [ref]$pidValue)) {
                return $pidValue
            }
        }
    }
    return $null
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
    if (($cmd -notmatch "client\.py") -and ($cmd -notmatch "voicepaste\.tray_app")) {
        return $null
    }
    if (($cmd -notmatch "VoicePaste") -and ($cmd -notmatch "voicepaste")) {
        return $null
    }

    return $proc
}

$pidValues = @()
$mainPid = Get-PidFromFiles -MetaPath $metaFile -PidPath $pidFile
if ($mainPid) {
    $pidValues += $mainPid
}
$trayPid = Get-PidFromFiles -MetaPath $trayMetaFile -PidPath $trayPidFile
if ($trayPid) {
    $pidValues += $trayPid
}

if (-not $pidValues) {
    $procMatches = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and (($_.CommandLine -match "client\.py") -or ($_.CommandLine -match "voicepaste\.tray_app"))
    }
    if ($procMatches) {
        foreach ($pm in $procMatches) {
            $pidValues += [int]$pm.ProcessId
        }
    }
}

$wasRunning = $false
foreach ($pidValue in ($pidValues | Select-Object -Unique)) {
    $proc = Test-VoicePasteProcess -PidValue $pidValue
    if ($proc) {
        $wasRunning = $true
        try {
            Stop-Process -Id $pidValue -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 500
        }
        catch {
        }

        $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
        }
    }
}

if (Test-Path $pidFile) {
    Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
}
if (Test-Path $metaFile) {
    Remove-Item -Path $metaFile -Force -ErrorAction SilentlyContinue
}
if (Test-Path $trayPidFile) {
    Remove-Item -Path $trayPidFile -Force -ErrorAction SilentlyContinue
}
if (Test-Path $trayMetaFile) {
    Remove-Item -Path $trayMetaFile -Force -ErrorAction SilentlyContinue
}

if ($wasRunning) {
    Write-Output "Voice Translator stopped"
}
else {
    Write-Output "Voice Translator not running"
}
