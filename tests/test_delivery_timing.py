import pytest
from unittest.mock import MagicMock
from voicepaste.delivery import paste_transcript

def test_paste_transcript_success_with_calibrated_sleep(monkeypatch):
    mock_set_fg = MagicMock(return_value=True)
    mock_get_fg = MagicMock(return_value=12345)
    mock_incr = MagicMock()
    mock_status = MagicMock()
    
    mock_keyboard_send = MagicMock()
    monkeypatch.setattr("voicepaste.delivery.keyboard.send", mock_keyboard_send)
    
    success = paste_transcript(
        target_hwnd=12345,
        paste_timeout_ms=500,
        set_foreground_window=mock_set_fg,
        increment_error=mock_incr,
        status=mock_status,
        get_foreground_window=mock_get_fg,
        verify_focus=True,
    )
    
    assert success is True
    mock_keyboard_send.assert_called_once_with("ctrl+v")
    mock_incr.assert_not_called()

def test_paste_transcript_suppressed_on_focus_loss(monkeypatch):
    mock_set_fg = MagicMock(return_value=True)
    mock_get_fg = MagicMock(return_value=99999) # Different HWND
    mock_incr = MagicMock()
    mock_status = MagicMock()
    mock_keyboard_send = MagicMock()
    monkeypatch.setattr("voicepaste.delivery.keyboard.send", mock_keyboard_send)
    
    success = paste_transcript(
        target_hwnd=12345,
        paste_timeout_ms=500,
        set_foreground_window=mock_set_fg,
        increment_error=mock_incr,
        status=mock_status,
        get_foreground_window=mock_get_fg,
        verify_focus=True,
    )
    
    assert success is False
    mock_keyboard_send.assert_not_called()
    assert mock_status.called
