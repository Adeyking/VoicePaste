' VoicePaste hidden launcher — runs the tray app with no visible window.
Dim fso, scriptDir, rootDir, shell
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
rootDir = fso.GetParentFolderName(scriptDir)
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = rootDir
shell.Run """" & rootDir & "\.venv\Scripts\pythonw.exe"" -m voicepaste.tray_app --config """ & rootDir & "\voicepaste.config.json""", 0, False

