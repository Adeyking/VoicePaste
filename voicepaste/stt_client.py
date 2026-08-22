import os
import time
from typing import Any, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_session = requests.Session()
_adapter = HTTPAdapter(
    pool_connections=10,
    pool_maxsize=10,
    max_retries=Retry(total=1, backoff_factor=0.05),
)
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)



def set_stt_token(token: str) -> None:
    if token:
        _session.headers["Authorization"] = f"Bearer {token.strip()}"
    elif "Authorization" in _session.headers:
        del _session.headers["Authorization"]


# Initial token load from environment if present
_env_token = os.getenv("STT_BEARER_TOKEN", "").strip() or os.getenv("STT_API_KEY", "").strip()
if _env_token:
    set_stt_token(_env_token)


def check_health(stt_health_url: str, stt_timeout_ms: int) -> bool:
    try:
        response = _session.get(stt_health_url, timeout=max(1.0, stt_timeout_ms / 1000.0))
        return response.status_code == 200 and response.json().get("status") == "ok"
    except Exception:
        return False


def transcribe_audio(
    stt_url: str,
    stt_timeout_ms: int,
    language: str,
    wav_bytes: bytes,
    initial_prompt: Optional[str] = None,
) -> Tuple[Optional[str], int, Optional[str]]:
    files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
    data = {"language": language}
    if initial_prompt:
        data["initial_prompt"] = initial_prompt
        data["prompt"] = initial_prompt
    started = time.perf_counter()
    try:
        response = _session.post(
            stt_url,
            files=files,
            data=data,
            timeout=max(1.0, stt_timeout_ms / 1000.0),
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return None, int((time.perf_counter() - started) * 1000), f"Transcription request failed: {exc}"

    try:
        payload: Any = response.json()
        raw_text = payload["text"]
        if not isinstance(raw_text, str):
            raise TypeError("'text' is not a string")
        return raw_text.strip(), int((time.perf_counter() - started) * 1000), None
    except Exception as exc:
        return None, int((time.perf_counter() - started) * 1000), f"Invalid transcription response: {exc}"


def transcribe_audio_stream_partial(
    stt_url: str,
    stt_timeout_ms: int,
    language: str,
    wav_bytes: bytes,
    initial_prompt: Optional[str] = None,
) -> Tuple[Optional[str], int, Optional[str]]:
    stream_url = stt_url.rstrip("/")
    if stream_url.endswith("/transcribe"):
        stream_url = stream_url[: -len("/transcribe")] + "/transcribe_stream"
    else:
        stream_url = f"{stream_url}/transcribe_stream"

    files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
    data = {"language": language}
    if initial_prompt:
        data["initial_prompt"] = initial_prompt
        data["prompt"] = initial_prompt
    started = time.perf_counter()
    try:
        response = _session.post(
            stream_url,
            files=files,
            data=data,
            timeout=min(max(0.5, stt_timeout_ms / 1000.0), 2.5),
        )

        response.raise_for_status()
    except requests.RequestException as exc:
        return None, int((time.perf_counter() - started) * 1000), f"Partial transcription request failed: {exc}"

    try:
        payload: Any = response.json()
        value = payload.get("partial_text", payload.get("partial", payload.get("text", "")))
        if not isinstance(value, str):
            raise TypeError("partial text is not a string")
        return value.strip(), int((time.perf_counter() - started) * 1000), None
    except Exception as exc:
        return None, int((time.perf_counter() - started) * 1000), f"Invalid partial transcription response: {exc}"


def transcribe_audio_gemini_free_fallback(
    api_key: str,
    wav_bytes: bytes,
    timeout_ms: int = 8000,
) -> Tuple[Optional[str], int, Optional[str]]:
    """Zero-cost fallback using Google AI Studio Free Tier (Gemini 2.5 Flash)."""
    import base64
    if not api_key:
        return None, 0, "No GEMINI_API_KEY provided"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": "Transcribe the following audio accurately. Output only the verbatim transcribed text and nothing else."},
                    {"inline_data": {"mime_type": "audio/wav", "data": audio_b64}},
                ]
            }
        ]
    }
    started = time.perf_counter()
    try:
        res = _session.post(url, json=payload, timeout=max(1.0, timeout_ms / 1000.0))
        res.raise_for_status()
        data = res.json()
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                text = parts[0].get("text", "").strip()
                return text, int((time.perf_counter() - started) * 1000), None
        return None, int((time.perf_counter() - started) * 1000), "No candidates returned from Gemini"
    except Exception as exc:
        return None, int((time.perf_counter() - started) * 1000), f"Gemini free fallback failed: {exc}"


def fetch_remote_vocabulary(stt_url: str, timeout_seconds: float = 2.0) -> Optional[dict]:
    """Fetch centralized vocabulary and phrase corrections from NucBox STT service."""
    base_url = stt_url.rstrip("/").removesuffix("/transcribe")
    vocab_url = f"{base_url}/api/v1/vocabulary"
    try:
        res = _session.get(vocab_url, timeout=(timeout_seconds, timeout_seconds * 2.5))
        if res.status_code == 200:
            return res.json()
        return None
    except Exception:
        return None


def push_vocabulary_correction(
    stt_url: str,
    original: str,
    replacement: str,
    timeout_seconds: float = 2.0,
) -> bool:
    """Push a new phrase correction pair to the central NucBox STT service."""
    if not original or not replacement:
        return False
    base_url = stt_url.rstrip("/").removesuffix("/transcribe")
    vocab_url = f"{base_url}/api/v1/vocabulary"
    payload = {"original": original.strip(), "replacement": replacement.strip()}
    try:
        res = _session.post(vocab_url, json=payload, timeout=(timeout_seconds, timeout_seconds * 2.5))
        return res.status_code == 200 and res.json().get("status") == "ok"
    except Exception:
        return False


def delete_vocabulary_correction(
    stt_url: str,
    original: str,
    timeout_seconds: float = 2.0,
) -> bool:
    """Delete a phrase correction pair from the central NucBox STT service."""
    if not original:
        return False
    base_url = stt_url.rstrip("/").removesuffix("/transcribe")
    vocab_url = f"{base_url}/api/v1/vocabulary"
    payload = {"original": original.strip()}
    try:
        res = _session.delete(vocab_url, json=payload, timeout=(timeout_seconds, timeout_seconds * 2.5))
        return res.status_code == 200 and res.json().get("status") == "ok"
    except Exception:
        return False



