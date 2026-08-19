# Clears old VoicePaste logs to maintain a fresh baseline for weekly dictation harvesting
$logDir = "$env:USERPROFILE\Documents\VoicePaste\Logs"
if (Test-Path $logDir) {
    $today = (Get-Date).ToString("yyyy-MM-dd")
    $files = Get-ChildItem -Path $logDir -Filter "voicepaste-*.log" | Where-Object { $_.Name -notmatch $today }
    foreach ($file in $files) {
        Remove-Item -Path $file.FullName -Force -ErrorAction SilentlyContinue
    }
    Write-Host "✅ Cleared $($files.Count) old log file(s). Fresh log baseline active starting today ($today)." -ForegroundColor Green
}
