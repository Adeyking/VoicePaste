$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$targetScript = Join-Path $PSScriptRoot "run_tray.ps1"
$iconPath = Join-Path $repoRoot "assets\voice_translator.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Voice Translator.lnk"
$legacyShortcutPath = Join-Path $desktop "VoicePaste Tray.lnk"

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-ExecutionPolicy Bypass -File `"$targetScript`""
$shortcut.WorkingDirectory = $repoRoot
if (Test-Path $iconPath) {
    $resolvedIconPath = (Resolve-Path $iconPath).Path
    $shortcut.IconLocation = "$resolvedIconPath,0"
}
else {
    $shortcut.IconLocation = "powershell.exe,0"
}
$shortcut.Description = "Launch Voice Translator tray app"
$shortcut.Save()

if (Test-Path $legacyShortcutPath) {
    Remove-Item -Path $legacyShortcutPath -Force -ErrorAction SilentlyContinue
}

Write-Output "Shortcut created: $shortcutPath"
