from types import SimpleNamespace

import requests
import pytest

from voicepaste.settings_window import SettingsWindow


def _window() -> SettingsWindow:
    cfg = SimpleNamespace(
        stt_url="http://127.0.0.1:8770/transcribe",
        ollama_url="http://127.0.0.1:11434",
        model_profile="fast",
        mode_default="dictation",
        voice_paste_root="voice_paste",
        ollama_keep_alive="20m",
        cloud_fallback_enabled=False,
        phrase_corrections_path="x.json",
        journal_path="journal",
        meeting_paste=False,
        audio_feedback=True,
    )
    return SettingsWindow(cfg, on_save=lambda _: None, on_edit_corrections=lambda: None)


def test_validate_http_url_rejects_bad_values() -> None:
    win = _window()
    with pytest.raises(ValueError):
        win._validate_http_url("STT URL", "")
    with pytest.raises(ValueError):
        win._validate_http_url("STT URL", "ftp://example.com")
    with pytest.raises(ValueError):
        win._validate_http_url("STT URL", "http:///missing-host")


def test_validate_settings_requires_reachable_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    win = _window()

    class Response:
        status_code = 200

    monkeypatch.setattr("voicepaste.settings_window.requests.get", lambda *a, **k: Response())
    win._validate_settings(
        {
            "STT_URL": "http://127.0.0.1:8770/transcribe",
            "OLLAMA_URL": "http://127.0.0.1:11434",
            "VOICE_PASTE_ROOT": "voice_paste",
        }
    )


def test_validate_settings_raises_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    win = _window()

    def _raise(*_args, **_kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr("voicepaste.settings_window.requests.get", _raise)
    monkeypatch.setattr("voicepaste.settings_window.messagebox.askyesno", lambda *a, **k: False)
    with pytest.raises(ValueError):
        win._validate_settings(
            {
                "STT_URL": "http://127.0.0.1:8770/transcribe",
                "OLLAMA_URL": "http://127.0.0.1:11434",
                "VOICE_PASTE_ROOT": "voice_paste",
            }
        )
