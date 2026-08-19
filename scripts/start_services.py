import os
import sys
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent.parent
py = root / ".venv" / "Scripts" / "python.exe"

import tempfile

tmp = Path(tempfile.gettempdir())
for lock in tmp.glob("voicepaste*.lock"):
    try:
        lock.unlink()
    except Exception:
        pass

for pid_f in (root / "scripts").glob("voicepaste*.pid"):
    try:
        pid_f.unlink()
    except Exception:
        pass

DETACHED = 0x00000008 | 0x00000200

# Launch VoicePaste tray_app cleanly in background without inheriting parent handles
p = subprocess.Popen(
    [str(py), "-m", "voicepaste.tray_app"],
    cwd=str(root),
    creationflags=DETACHED,
)
print(f"VoicePaste native process launched with PID {p.pid}")
