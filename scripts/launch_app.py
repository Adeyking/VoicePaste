import os
import sys
import subprocess
from pathlib import Path

import tempfile

root = Path(__file__).resolve().parent.parent
py = root / ".venv" / "Scripts" / "pythonw.exe"
if not py.exists():
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

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

p = subprocess.Popen(
    [str(py), "-m", "voicepaste.tray_app", "--config", str(root / "voicepaste.config.json")],
    cwd=str(root),
    creationflags=flags,
    close_fds=True,
)
print(f"Launched VoicePaste with PID {p.pid}")
