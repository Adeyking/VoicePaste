# Scans fresh VoicePaste logs for raw vs corrected transcript differences to harvest new misheard words
$logDir = "$env:USERPROFILE\Documents\VoicePaste\Logs"
if (-not (Test-Path $logDir)) {
    Write-Host "No logs directory found." -ForegroundColor Yellow
    exit 0
}

$logFiles = Get-ChildItem -Path $logDir -Filter "voicepaste-*.log" | Sort-Object LastWriteTime
Write-Host "🔍 Scanning $($logFiles.Count) log file(s) for misheard words and corrections..." -ForegroundColor Cyan

$count = 0
foreach ($file in $logFiles) {
    $lines = Get-Content -Path $file.FullName -ErrorAction SilentlyContinue
    foreach ($line in $lines) {
        if ($line -match 'EVENT (\{.*\})') {
            try {
                $evt = $matches[1] | ConvertFrom-Json
                $raw = [string]$evt.stt_text_raw
                $corrected = [string]$evt.stt_text_corrected
                $corrections = $evt.corrections_applied
                
                if ($raw -and $corrected -and ($raw.Trim() -ne $corrected.Trim() -or $corrections.Count -gt 0)) {
                    $count++
                    Write-Host "----------------------------------------" -ForegroundColor Gray
                    Write-Host "📅 Date: $($evt.timestamp) | Utterance: u$($evt.utterance_id)" -ForegroundColor Yellow
                    Write-Host "🎙️ Raw STT:       $raw" -ForegroundColor White
                    Write-Host "✏️ Corrected STT: $corrected" -ForegroundColor Green
                    if ($corrections) {
                        Write-Host "🔧 Corrections:   $($corrections -join ', ')" -ForegroundColor Cyan
                    }
                }
            } catch {}
        }
    }
}

if ($count -eq 0) {
    Write-Host "✨ No unmapped misheard words found in recent logs!" -ForegroundColor Green
} else {
    Write-Host "----------------------------------------" -ForegroundColor Gray
    Write-Host "📊 Found $count candidate utterance(s) with corrections/mishearings." -ForegroundColor Green
}
