import pytest
from voicepaste.engine import extract_window_context, get_window_title_from_hwnd


def test_extract_window_context_vscode() -> None:
    title = "app.py - home-dashboard-smoke - Visual Studio Code"
    tokens = extract_window_context(title)
    assert "app.py" in tokens
    assert "home-dashboard-smoke" in tokens
    assert "Visual Studio Code" not in tokens
    assert len(tokens) <= 3


def test_extract_window_context_obsidian() -> None:
    title = "03_Tech - Obsidian v1.6.7"
    tokens = extract_window_context(title)
    assert "03_Tech" in tokens
    assert "Obsidian" not in tokens


def test_extract_window_context_browser_with_delimiters() -> None:
    title = "Claude Code | Anthropic - Google Chrome"
    tokens = extract_window_context(title)
    assert "Claude" in tokens
    assert "Code" in tokens or "Anthropic" in tokens
    assert "Google Chrome" not in tokens


def test_extract_window_context_emojis_and_symbols() -> None:
    title = "⚡ Crypto-Trading-Bot 🔥 - Visual Studio Code"
    tokens = extract_window_context(title)
    assert "Crypto-Trading-Bot" in tokens


def test_extract_window_context_edge_cases() -> None:
    # None or empty
    assert extract_window_context(None) == []
    assert extract_window_context("") == []
    assert extract_window_context("   ") == []

    # Pure application name with no project
    assert extract_window_context("Visual Studio Code") == []
    assert extract_window_context("Google Chrome") == []
    assert extract_window_context("Obsidian v1.6.7") == []

    # All numeric
    assert extract_window_context("12345 - Visual Studio Code") == []


def test_get_window_title_from_hwnd_null_safety() -> None:
    # Null / 0 HWND returns empty string safely
    assert get_window_title_from_hwnd(None) == ""
    assert get_window_title_from_hwnd(0) == ""


def test_get_window_title_from_hwnd_mock(monkeypatch) -> None:
    class MockUser32:
        @staticmethod
        def GetWindowTextLengthW(hwnd):
            return 11 if hwnd == 1234 else 0

        @staticmethod
        def GetWindowTextW(hwnd, buf, maxlen):
            if hwnd == 1234:
                buf.value = "Test Window"
                return 11
            return 0

    monkeypatch.setattr("voicepaste.engine.USER32", MockUser32)
    assert get_window_title_from_hwnd(1234) == "Test Window"
    assert get_window_title_from_hwnd(9999) == ""

