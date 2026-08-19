param (
    [Parameter(Mandatory=$true, Position=0)]
    [string]$Wrong,
    
    [Parameter(Mandatory=$true, Position=1)]
    [string]$Right
)

$ErrorActionPreference = "Stop"

$Path = "$env:USERPROFILE\Documents\VoicePaste\phrase_corrections.json"
if (-not (Test-Path $Path)) {
    @{ exact = @{}; regex = @() } | ConvertTo-Json -Depth 5 | Set-Content -Path $Path -Encoding UTF8
}

$JsonText = Get-Content -Path $Path -Raw -Encoding UTF8
$Data = $JsonText | ConvertFrom-Json

if (-not $Data.exact) {
    $Data | Add-Member -NotePropertyName "exact" -NotePropertyValue (New-Object PSObject)
}

$Key = $Wrong.Trim().ToLower()
$Val = $Right.Trim()

$Data.exact | Add-Member -NotePropertyName $Key -NotePropertyValue $Val -Force

$Updated = $Data | ConvertTo-Json -Depth 5
Set-Content -Path $Path -Value $Updated -Encoding UTF8

Write-Host "✅ Added phrase correction: '$Key' -> '$Val' in $Path" -ForegroundColor Green

# Synchronize with STT Service if online
try {
    $SttUrl = if ($env:STT_URL) { "$env:STT_URL/api/v1/vocabulary" } else { "http://localhost:8770/api/v1/vocabulary" }
    $Body = @{ original = $Key; replacement = $Val } | ConvertTo-Json
    $null = Invoke-RestMethod -Uri $SttUrl -Method Post -Body $Body -ContentType "application/json" -TimeoutSec 2 -ErrorAction SilentlyContinue
    Write-Host "⚡ Synchronized '$Key' -> '$Val' to STT service" -ForegroundColor Cyan
} catch {
    # Fail silently if NucBox is off-LAN
}

