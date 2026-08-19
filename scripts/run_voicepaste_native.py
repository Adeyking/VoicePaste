import os
import sys
import subprocess
from pathlib import Path

import tempfile

root = Path(__file__).resolve().parent.parent
py = root / ".venv" / "Scripts" / "python.exe"
if not py.exists():
    py = Path(sys.executable)

# Clean locks
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

p = subprocess.Popen(
    [str(py), "-m", "voicepaste.tray_app", "--config", str(root / "voicepaste.config.json")],
    cwd=str(root),
    creationflags=DETACHED,
)
print(f"Successfully launched VoicePaste Native Process with PID {p.pid}")
