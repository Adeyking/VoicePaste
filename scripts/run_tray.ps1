param(
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $PSScriptRoot "voicepaste.tray.pid"
$metaFile = Join-Path $PSScriptRoot "voicepaste.tray.process.json"
$legacyPidFile = Join-Path $PSScriptRoot "voicepaste.pid"
$legacyMetaFile = Join-Path $PSScriptRoot "voicepaste.process.json"

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

function Test-TrayProcess {
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

    if ($cmd -notmatch "voicepaste\.tray_app") {
        return $null
    }

    return $proc
}

function Find-ExistingTrayProcesses {
    $procInfos = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -in @("python.exe", "pythonw.exe") -and
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

function Find-ExistingCliProcesses {
    $procInfos = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -in @("python.exe", "pythonw.exe") -and
        $_.CommandLine -and
        $_.CommandLine -match "client\.py" -and
        $_.CommandLine -match "VoicePaste"
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
    $existing = Test-TrayProcess -PidValue $existingPid
    if ($existing) {
        $runningTrays = @(Find-ExistingTrayProcesses)
        $duplicates = $runningTrays | Where-Object { $_.Id -ne $existingPid }
        foreach ($dup in $duplicates) {
            try {
                Stop-Process -Id $dup.Id -Force -ErrorAction SilentlyContinue
            }
            catch {
            }
        }
        Write-Output "Voice Translator tray already running (PID $existingPid)"
        exit 0
    }
}

$existingByScan = @(Find-ExistingTrayProcesses)
if ($existingByScan.Count -gt 0) {
    $primary = $existingByScan | Sort-Object StartTime | Select-Object -First 1
    $duplicates = $existingByScan | Where-Object { $_.Id -ne $primary.Id }
    foreach ($dup in $duplicates) {
        try {
            Stop-Process -Id $dup.Id -Force -ErrorAction SilentlyContinue
        }
        catch {
        }
    }

    $runningPid = [int]$primary.Id
    Set-Content -Path $pidFile -Value $runningPid -Encoding ASCII
    $meta = [pscustomobject]@{
        pid = $runningPid
        started_at = (Get-Date).ToString("o")
        config_path = $resolvedConfigPath
    }
    $meta | ConvertTo-Json | Set-Content -Path $metaFile -Encoding UTF8
    Write-Output "Voice Translator tray already running (PID $runningPid)"
    exit 0
}

$runningCli = @(Find-ExistingCliProcesses)
if ($runningCli.Count -gt 0) {
    foreach ($proc in $runningCli) {
        try {
            Stop-Process -Id $proc.Id -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 300
        }
        catch {
        }
        $stillRunning = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
        if ($stillRunning) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Output ("Stopped legacy CLI process(es): " + (($runningCli | Sort-Object Id | ForEach-Object { $_.Id }) -join ", "))
    Remove-Item -Path $legacyPidFile -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $legacyMetaFile -Force -ErrorAction SilentlyContinue
}

if (Test-Path $pidFile) {
    Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
}
if (Test-Path $metaFile) {
    Remove-Item -Path $metaFile -Force -ErrorAction SilentlyContinue
}

function Get-PythonCandidates {
    $candidates = New-Object System.Collections.Generic.List[string]
    $repoVenvCandidates = New-Object System.Collections.Generic.List[string]

    function Add-Candidate {
        param(
            [string]$CandidatePath,
            [switch]$IsRepoVenv
        )
        if (-not $CandidatePath) {
            return
        }
        if (-not (Test-Path $CandidatePath -PathType Leaf)) {
            return
        }
        if (-not $candidates.Contains($CandidatePath)) {
            $candidates.Add($CandidatePath)
        }
        if ($IsRepoVenv -and -not $repoVenvCandidates.Contains($CandidatePath)) {
            $repoVenvCandidates.Add($CandidatePath)
        }
    }

    Add-Candidate (Join-Path $repoRoot ".venv\Scripts\pythonw.exe") -IsRepoVenv
    Add-Candidate (Join-Path $repoRoot ".venv\Scripts\python.exe") -IsRepoVenv
    Add-Candidate (Join-Path $repoRoot ".venv314\Scripts\pythonw.exe") -IsRepoVenv
    Add-Candidate (Join-Path $repoRoot ".venv314\Scripts\python.exe") -IsRepoVenv
    Add-Candidate (Join-Path $repoRoot ".venv313\Scripts\python.exe") -IsRepoVenv
    Add-Candidate (Join-Path $repoRoot ".venv312\Scripts\python.exe") -IsRepoVenv
    Add-Candidate (Join-Path $repoRoot ".venv311\Scripts\python.exe") -IsRepoVenv

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd -and $pythonCmd.Source) {
        Add-Candidate $pythonCmd.Source
    }

    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd -and $pyCmd.Source) {
        foreach ($version in @("3.14", "3.13", "3.12", "3.11")) {
            try {
                $resolved = & $pyCmd.Source "-$version" "-c" "import sys;print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $resolved) {
                    $resolvedPath = ($resolved | Select-Object -First 1).Trim()
                    Add-Candidate $resolvedPath
                }
            }
            catch {
            }
        }
    }

    return [pscustomobject]@{
        Candidates = $candidates
        RepoVenvCandidates = $repoVenvCandidates
    }
}

function Test-PythonHasTrayDeps {
    param([string]$PythonPath)

    # Uses Start-Process + external script to avoid PowerShell pipeline restriction
    # that blocks venv launcher executables (py.exe stub) when used in pipelines.
    $checkScript = Join-Path $PSScriptRoot "check_tray_deps.py"
    try {
        $proc = Start-Process -FilePath $PythonPath -ArgumentList "`"$checkScript`"" -WindowStyle Hidden -PassThru -Wait
        return ($proc.ExitCode -eq 0)
    }
    catch {
        return $false
    }
}

$selectedPython = $null
$pythonCandidateInfo = Get-PythonCandidates
$pythonCandidates = $pythonCandidateInfo.Candidates
$repoVenvCandidates = $pythonCandidateInfo.RepoVenvCandidates

foreach ($candidate in $repoVenvCandidates) {
    if (Test-PythonHasTrayDeps -PythonPath $candidate) {
        $selectedPython = $candidate
        break
    }
}

if (-not $selectedPython -and $repoVenvCandidates.Count -gt 0) {
    Write-Output "Voice Translator tray failed: project virtualenv exists but is missing runtime dependencies. Reinstall with: .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}

if (-not $selectedPython) {
    foreach ($candidate in $pythonCandidates) {
        if (Test-PythonHasTrayDeps -PythonPath $candidate) {
            $selectedPython = $candidate
            break
        }
    }
}

if (-not $selectedPython) {
    Write-Output "Voice Translator tray failed: missing runtime dependencies. Install with: py -3.14 -m pip install -r requirements.txt"
    exit 1
}

$args = @("-m", "voicepaste.tray_app", "--config", $resolvedConfigPath)
$proc = Start-Process -FilePath $selectedPython -ArgumentList $args -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru

Set-Content -Path $pidFile -Value $proc.Id -Encoding ASCII
$meta = [pscustomobject]@{
    pid = $proc.Id
    started_at = (Get-Date).ToString("o")
    config_path = $resolvedConfigPath
    python_path = $selectedPython
}
$meta | ConvertTo-Json | Set-Content -Path $metaFile -Encoding UTF8

Write-Output "Voice Translator tray started (PID $($proc.Id)) using $selectedPython"
