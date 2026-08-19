from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict


def prune_old_logs(log_dir: str, retention_days: int, now: datetime | None = None) -> Dict[str, int]:
    if retention_days <= 0:
        return {"scanned": 0, "deleted": 0, "retention_days": retention_days}

    root = Path(log_dir)
    if not root.exists() or not root.is_dir():
        return {"scanned": 0, "deleted": 0, "retention_days": retention_days}

    if now is None:
        now = datetime.now()
    cutoff = now - timedelta(days=retention_days)
    today_file = f"voicepaste-{now.strftime('%Y-%m-%d')}.log"

    scanned = 0
    deleted = 0
    for path in root.glob("voicepaste-*.log"):
        scanned += 1
        if path.name == today_file:
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                path.unlink()
                deleted += 1
            except OSError:
                continue

    return {"scanned": scanned, "deleted": deleted, "retention_days": retention_days}
