import os
import subprocess
from pathlib import Path

vbs_path = Path(__file__).resolve().parent / "autostart_voicepaste.vbs"
cmd = f'schtasks /create /tn "VoicePaste" /tr "wscript.exe \\"{str(vbs_path)}\\"" /sc onlogon /rl limited /f'

print("Running command:", cmd)
res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
print("STDOUT:", res.stdout)
print("STDERR:", res.stderr)

if res.returncode == 0:
    run_res = subprocess.run('schtasks /run /tn "VoicePaste"', shell=True, capture_output=True, text=True)
    print("RUN STDOUT:", run_res.stdout)
    print("RUN STDERR:", run_res.stderr)
