import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Safe defaults for headless test runners
os.environ.setdefault("VOICEPASTE_STT_URL", "http://localhost:8770")
os.environ.setdefault("VOICEPASTE_OLLAMA_URL", "http://localhost:11434")
