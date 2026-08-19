from typing import List, Tuple
from voicepaste.delivery import paste_transcript


def test_paste_transcript_suppressed_when_focus_shifts() -> None:
    statuses: List[Tuple[str, str]] = []
    errors: List[str] = []

    def mock_status(state: str, message: str) -> None:
        statuses.append((state, message))

    def mock_set_fg(hwnd: int) -> bool:
        return True

    def mock_get_fg() -> int:
        return 9999  # Current window differs from target (1234)

    result = paste_transcript(
        target_hwnd=1234,
        paste_timeout_ms=500,
        set_foreground_window=mock_set_fg,
        increment_error=lambda err: errors.append(err),
        status=mock_status,
        get_foreground_window=mock_get_fg,
        verify_focus=True,
    )

    assert result is False
    assert any(st == "PASTE_GUARD" for st, _ in statuses)
    assert len(errors) == 0


def test_paste_transcript_proceeds_when_focus_matches(monkeypatch) -> None:
    statuses: List[Tuple[str, str]] = []
    sent_keys: List[str] = []

    def mock_status(state: str, message: str) -> None:
        statuses.append((state, message))

    def mock_set_fg(hwnd: int) -> bool:
        return True

    def mock_get_fg() -> int:
        return 1234  # Current matches target (1234)

    monkeypatch.setattr("voicepaste.delivery.keyboard.send", lambda key: sent_keys.append(key))

    result = paste_transcript(
        target_hwnd=1234,
        paste_timeout_ms=500,
        set_foreground_window=mock_set_fg,
        increment_error=lambda _: None,
        status=mock_status,
        get_foreground_window=mock_get_fg,
        verify_focus=True,
    )

    assert result is True
    assert "ctrl+v" in sent_keys
    assert not any(st == "PASTE_GUARD" for st, _ in statuses)


def test_paste_transcript_bypasses_guard_when_disabled(monkeypatch) -> None:
    statuses: List[Tuple[str, str]] = []
    sent_keys: List[str] = []

    def mock_status(state: str, message: str) -> None:
        statuses.append((state, message))

    def mock_set_fg(hwnd: int) -> bool:
        return True

    def mock_get_fg() -> int:
        return 9999  # Shifted focus

    monkeypatch.setattr("voicepaste.delivery.keyboard.send", lambda key: sent_keys.append(key))

    result = paste_transcript(
        target_hwnd=1234,
        paste_timeout_ms=500,
        set_foreground_window=mock_set_fg,
        increment_error=lambda _: None,
        status=mock_status,
        get_foreground_window=mock_get_fg,
        verify_focus=False,
    )

    assert result is True
    assert "ctrl+v" in sent_keys
