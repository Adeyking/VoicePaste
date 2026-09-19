import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from voicepaste.engine import get_clipboard_candidate_terms, PushToTalkClient, VoicePasteConfig, build_parser


def test_get_clipboard_candidate_terms_valid() -> None:
    with patch("pyperclip.paste", return_value="Check the Substation7 project in CEng"):
        candidates = get_clipboard_candidate_terms(max_terms=2)
        assert "Substation7" in candidates
        assert "CEng" in candidates


def test_get_clipboard_candidate_terms_stops_and_numbers() -> None:
    with patch("pyperclip.paste", return_value="12345 the and that with 9999"):
        candidates = get_clipboard_candidate_terms(max_terms=2)
        assert candidates == []


def test_get_clipboard_candidate_terms_huge_text_guardrail() -> None:
    # Huge text > 500 chars is safely ignored to protect prompt token limits
    huge_text = "Word " * 120
    with patch("pyperclip.paste", return_value=huge_text):
        candidates = get_clipboard_candidate_terms(max_terms=2)
        assert candidates == []


def test_get_clipboard_candidate_terms_exception_safety() -> None:
    with patch("pyperclip.paste", side_effect=Exception("Clipboard locked")):
        candidates = get_clipboard_candidate_terms(max_terms=2)
        assert candidates == []


def test_auto_stop_guardrail_triggers_stop() -> None:
    args = build_parser().parse_args([])
    cfg = VoicePasteConfig.load(args)
    client = PushToTalkClient(cfg)
    client._recording = True
    client.stop_recording = MagicMock()

    client._auto_stop_guardrail()
    client.stop_recording.assert_called_once()


def test_quick_save_clipboard_vocabulary_length_limit(tmp_path: Path) -> None:
    args = build_parser().parse_args([])
    cfg = VoicePasteConfig.load(args)
    client = PushToTalkClient(cfg)
    statuses: list[tuple[str, str]] = []
    client._status = lambda s, m, *a: statuses.append((s, m))

    # Text > 50 characters is rejected
    with patch("pyperclip.paste", return_value="A" * 60):
        client.quick_save_clipboard_vocabulary()
        assert any(s[0] == "WARNING" for s in statuses)

    # Valid term is added
    with patch("pyperclip.paste", return_value="SubstationAlpha"):
        with patch("urllib.request.urlopen"):
            client.quick_save_clipboard_vocabulary()
            assert any("SubstationAlpha" in s[1] for s in statuses if s[0] == "SAVED")
            assert any(k == "substationalpha" and v == "SubstationAlpha" for k, v in client._phrase_exact)
