from datetime import datetime, timedelta
from pathlib import Path

from voicepaste.log_utils import prune_old_logs


def _touch_with_age(path: Path, days_old: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    ts = (datetime.now() - timedelta(days=days_old)).timestamp()
    path.touch()
    Path(path).stat()
    import os

    os.utime(path, (ts, ts))


def test_prune_old_logs_disabled(tmp_path: Path) -> None:
    old_log = tmp_path / "voicepaste-2020-01-01.log"
    _touch_with_age(old_log, 999)
    result = prune_old_logs(str(tmp_path), 0)
    assert result["deleted"] == 0
    assert old_log.exists()


def test_prune_old_logs_deletes_only_beyond_threshold(tmp_path: Path) -> None:
    old_log = tmp_path / "voicepaste-2020-01-01.log"
    recent_log = tmp_path / "voicepaste-2099-01-01.log"
    _touch_with_age(old_log, 45)
    _touch_with_age(recent_log, 2)

    now = datetime.now()
    result = prune_old_logs(str(tmp_path), 30, now=now)
    assert result["scanned"] >= 2
    assert result["deleted"] == 1
    assert not old_log.exists()
    assert recent_log.exists()


def test_prune_old_logs_ignores_missing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    result = prune_old_logs(str(missing), 30)
    assert result == {"scanned": 0, "deleted": 0, "retention_days": 30}


def test_prune_old_logs_ignores_non_matching_files(tmp_path: Path) -> None:
    other = tmp_path / "random.log"
    _touch_with_age(other, 400)
    result = prune_old_logs(str(tmp_path), 30)
    assert result["scanned"] == 0
    assert result["deleted"] == 0
    assert other.exists()


def test_prune_old_logs_keeps_today_file_even_if_old_timestamp(tmp_path: Path) -> None:
    now = datetime.now()
    today_name = f"voicepaste-{now.strftime('%Y-%m-%d')}.log"
    today_log = tmp_path / today_name
    _touch_with_age(today_log, 400)
    result = prune_old_logs(str(tmp_path), 30, now=now)
    assert result["scanned"] == 1
    assert result["deleted"] == 0
    assert today_log.exists()
