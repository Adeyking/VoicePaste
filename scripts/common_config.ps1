function Get-VoicePasteDefaults {
    param(
        [string]$RepoRoot
    )

    $fallback = [ordered]@{
        STT_URL = "http://localhost:8770/transcribe"
        OLLAMA_URL = "http://localhost:11434"
        LOG_DIR = "%USERPROFILE%\\Documents\\VoicePaste\\Logs"
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCmd) {
        return [pscustomobject]$fallback
    }

    $code = @'
import importlib.util
import json
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
defaults_path = repo_root / "voicepaste" / "defaults.py"
spec = importlib.util.spec_from_file_location("voicepaste_defaults", defaults_path)
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(module)

print(json.dumps({
    "STT_URL": module.DEFAULT_STT_URL,
    "OLLAMA_URL": module.DEFAULT_OLLAMA_URL,
    "LOG_DIR": module.DEFAULT_LOG_DIR,
}))
'@

    try {
        $json = & $pythonCmd.Source -c $code $RepoRoot 2>$null
        if ($LASTEXITCODE -eq 0 -and $json) {
            $parsed = $json | ConvertFrom-Json
            if ($parsed.STT_URL -and $parsed.OLLAMA_URL -and $parsed.LOG_DIR) {
                return $parsed
            }
        }
    }
    catch {
    }

    return [pscustomobject]$fallback
}

function Get-VoicePasteResolvedConfig {
    param(
        [string]$ConfigPath,
        [string]$RepoRoot,
        [switch]$ApplyEnvOverrides
    )

    $defaults = Get-VoicePasteDefaults -RepoRoot $RepoRoot
    $resolved = [ordered]@{
        STT_URL = [string]$defaults.STT_URL
        OLLAMA_URL = [string]$defaults.OLLAMA_URL
        LOG_DIR = [string]$defaults.LOG_DIR
    }

    if (Test-Path $ConfigPath) {
        try {
            $cfg = Get-Content -Path $ConfigPath -Raw | ConvertFrom-Json
            if ($cfg.STT_URL) { $resolved.STT_URL = [string]$cfg.STT_URL }
            if ($cfg.OLLAMA_URL) { $resolved.OLLAMA_URL = [string]$cfg.OLLAMA_URL }
            if ($cfg.LOG_DIR) { $resolved.LOG_DIR = [string]$cfg.LOG_DIR }
        }
        catch {
        }
    }

    if ($ApplyEnvOverrides) {
        if ($env:STT_URL) { $resolved.STT_URL = $env:STT_URL }
        if ($env:OLLAMA_URL) { $resolved.OLLAMA_URL = $env:OLLAMA_URL }
    }

    return [pscustomobject]$resolved
}

function Get-SttHealthUrl {
    param(
        [string]$SttUrl
    )

    if ($SttUrl.EndsWith("/transcribe")) {
        return ($SttUrl.Substring(0, $SttUrl.Length - "/transcribe".Length) + "/health")
    }

    return ($SttUrl.TrimEnd("/") + "/health")
}
