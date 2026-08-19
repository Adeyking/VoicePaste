import pytest
from unittest.mock import MagicMock, patch
import requests

from voicepaste.stt_client import (
    delete_vocabulary_correction,
    fetch_remote_vocabulary,
    push_vocabulary_correction,
)


def test_fetch_remote_vocabulary_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "ok",
        "count": 2,
        "phrase_corrections": {"nuc box": "NucBox", "qwen": "Qwen"},
        "initial_prompt": "NucBox, Qwen",
    }

    with patch("voicepaste.stt_client._session.get", return_value=mock_response) as mock_get:
        data = fetch_remote_vocabulary("http://127.0.0.1:8770/transcribe")
        assert data is not None
        assert data["status"] == "ok"
        assert data["count"] == 2
        assert data["phrase_corrections"]["nuc box"] == "NucBox"
        mock_get.assert_called_once_with(
            "http://127.0.0.1:8770/api/v1/vocabulary",
            timeout=(2.0, 5.0),
        )


def test_push_vocabulary_correction_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok", "added_or_updated": 1, "count": 5}

    with patch("voicepaste.stt_client._session.post", return_value=mock_response) as mock_post:
        success = push_vocabulary_correction("http://127.0.0.1:8770/transcribe", "nuc box", "NucBox")
        assert success is True
        mock_post.assert_called_once_with(
            "http://127.0.0.1:8770/api/v1/vocabulary",
            json={"original": "nuc box", "replacement": "NucBox"},
            timeout=(2.0, 5.0),
        )


def test_delete_vocabulary_correction_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok", "deleted": True, "key": "nuc box", "count": 4}

    with patch("voicepaste.stt_client._session.delete", return_value=mock_response) as mock_delete:
        success = delete_vocabulary_correction("http://127.0.0.1:8770/transcribe", "nuc box")
        assert success is True
        mock_delete.assert_called_once_with(
            "http://127.0.0.1:8770/api/v1/vocabulary",
            json={"original": "nuc box"},
            timeout=(2.0, 5.0),
        )


def test_network_timeout_and_connection_error_failover():
    # Timeout
    with patch("voicepaste.stt_client._session.get", side_effect=requests.exceptions.Timeout("Connection timed out")):
        assert fetch_remote_vocabulary("http://127.0.0.1:8770/transcribe") is None

    # ConnectionRefusedError
    with patch("voicepaste.stt_client._session.post", side_effect=requests.exceptions.ConnectionError("Connection refused")):
        assert push_vocabulary_correction("http://127.0.0.1:8770/transcribe", "test", "Test") is False

    # Delete connection error
    with patch("voicepaste.stt_client._session.delete", side_effect=requests.exceptions.ConnectionError("Connection refused")):
        assert delete_vocabulary_correction("http://127.0.0.1:8770/transcribe", "test") is False


def test_malformed_payload_handling():
    # Empty inputs
    assert push_vocabulary_correction("http://127.0.0.1:8770/transcribe", "", "NucBox") is False
    assert push_vocabulary_correction("http://127.0.0.1:8770/transcribe", "nuc box", "") is False
    assert delete_vocabulary_correction("http://127.0.0.1:8770/transcribe", "") is False

    # HTTP 400 Bad Request response from server
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"detail": "Invalid payload"}

    with patch("voicepaste.stt_client._session.post", return_value=mock_response):
        assert push_vocabulary_correction("http://127.0.0.1:8770/transcribe", "bad", "Bad") is False
