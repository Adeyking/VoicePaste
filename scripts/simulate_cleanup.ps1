param(
    [string]$ConfigPath = "",
    [string]$InputFile = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repoRoot "voicepaste.config.json"
}
$resolvedConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)

if (-not (Test-Path $resolvedConfigPath)) {
    Write-Output "Config not found: $resolvedConfigPath"
    exit 1
}

$samples = @(
    "This is a test. for the FAST model. I'm testing the quality of the output from the new voice model. Mmm. I hope it's good.",
    "This is a test for the quality model. I'm testing the quality of the output for the new model. I hope it's good. Much better.",
    "Are you going to work any better? Are you going to work any better? Yeah, brilliant. Let's see how you do.",
    "Please send the email please send the email to John to John by noon by noon"
)

if ($InputFile -and (Test-Path $InputFile)) {
    $samples = Get-Content -Path $InputFile | Where-Object { $_.Trim() -ne "" }
}

$tmpPayload = Join-Path $env:TEMP ("voice-translator-samples-" + [Guid]::NewGuid().ToString("N") + ".json")
$samples | ConvertTo-Json | Set-Content -Path $tmpPayload -Encoding UTF8

@'
import argparse
import json
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
config_path = Path(sys.argv[2])
payload_path = Path(sys.argv[3])
payload = json.loads(payload_path.read_text(encoding="utf-8-sig"))

sys.path.insert(0, str(repo_root))
from voicepaste.engine import VoicePasteConfig, PushToTalkClient, build_parser  # noqa: E402

parser = build_parser()
args = parser.parse_args([])
args.config = str(config_path)

cfg = VoicePasteConfig.load(args)
client = PushToTalkClient(cfg)

for idx, sample in enumerate(payload, start=1):
    deduped = client._post_clean_dedupe(sample)
    polished = client._light_post_polish(deduped)
    print(f"--- Sample {idx} ---")
    print("IN :", sample)
    print("OUT:", polished)
'@ | python - "$repoRoot" "$resolvedConfigPath" "$tmpPayload"

Remove-Item -Path $tmpPayload -Force -ErrorAction SilentlyContinue
