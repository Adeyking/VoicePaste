Dim fso, rootDir, shell
Set fso = CreateObject("Scripting.FileSystemObject")
rootDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = rootDir
shell.Run """" & rootDir & "\.venv\Scripts\pythonw.exe"" """ & rootDir & "\voicepaste_config_api.py""", 0, False
