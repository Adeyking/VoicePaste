# How to use:
# Run this script and hold Ctrl + Numpad 0 to record speech.
# Release either key to transcribe, clean (local-first), and paste.

import argparse
import ctypes
import io
import json
import logging
import os
import re
import sys
import threading
import time
import wave
from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
)
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

import keyboard
import numpy as np
import pyperclip
import requests
import sounddevice as sd
import winsound

from .cleanup import (
    assistant_prompt as build_assistant_prompt,
    call_claude_generate,
    call_ollama_generate,
    check_model_loaded_in_vram,
    quality_cleanup_prompt,
    strict_cleanup_prompt,
)
from . import defaults
from .delivery import append_to_journal, append_to_transcript_file, paste_transcript
from .log_utils import prune_old_logs
from .partial_stabilizer import PartialTranscriptStabilizer
from .stt_client import check_health as stt_check_health, transcribe_audio
from .stt_client import (
    fetch_remote_vocabulary,
    push_vocabulary_correction,
    transcribe_audio_stream_partial,
)

from .snippets import apply_snippets, load_snippets
from .text_processing import (
    apply_phrase_corrections,
    dedupe_consecutive_sentences,
    dedupe_repeated_ngrams,
    light_post_polish,
    post_clean_dedupe,
    sanitize_model_output,
)
from .voice_commands import apply_voice_commands
from .vad import detect_silence_window, wait_for_silence
from .hud import FloatingHUD
from .version import __version__

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
PTT_KEY_ALIASES = {
    "ctrl": "ctrl",
    "left ctrl": "ctrl",
    "right ctrl": "ctrl",
    "lctrl": "ctrl",
    "rctrl": "ctrl",
    "alt": "alt",
    "left alt": "alt",
    "right alt": "alt",
    "lalt": "alt",
    "ralt": "alt",
    "0": "num0",
    "num 0": "num0",
    "numpad 0": "num0",
    "kp 0": "num0",
    "num0": "num0",
    "insert": "num0",
}
PTT_KEY_SCAN_CODES = {
    29: "ctrl",
    3613: "ctrl",
    56: "alt",
    3640: "alt",
    11: "num0",
    82: "num0",
}
PTT_PRIMARY_CHORD_KEYS = {"ctrl", "alt"}
PTT_FALLBACK_CHORD_KEYS = {"ctrl", "num0"}
_FALLBACK_ALERT_THRESHOLD = 3  # tray ERROR notification after this many consecutive cleanup fallbacks
VALID_MODES = {"dictation", "assistant", "journal", "meeting"}
VALID_PROFILES = {"neutral", "email", "chat"}
VALID_MODEL_PROFILES = {"verbatim", "fast", "quality"}
VALID_APP_MODES = {"tray", "cli"}
MODE_HOTKEYS = {
    "dictation": "ctrl+alt+1",
    "assistant": "ctrl+alt+2",
    "journal": "ctrl+alt+3",
    "meeting": "ctrl+alt+9",
}
PROFILE_HOTKEYS = {
    "neutral": "ctrl+alt+6",
    "email": "ctrl+alt+4",
    "chat": "ctrl+alt+5",
}
MODEL_HOTKEYS = {
    "fast": "ctrl+alt+7",
    "quality": "ctrl+alt+8",
}
DEFAULT_QUIT_HOTKEY = "ctrl+alt+q"

USER32 = ctypes.windll.user32
USER32.GetForegroundWindow.restype = wintypes.HWND
USER32.SetForegroundWindow.argtypes = [wintypes.HWND]
USER32.SetForegroundWindow.restype = wintypes.BOOL
USER32.GetAsyncKeyState.argtypes = [wintypes.INT]
USER32.GetAsyncKeyState.restype = wintypes.SHORT


def _safe_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _safe_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    if parsed < minimum:
        return default
    return parsed


def _expand_path(value: str) -> str:
    return os.path.expandvars(os.path.expanduser(value))


def _parse_keep_alive_s(keep_alive: str) -> float:
    """Convert an Ollama keep_alive string (e.g. '20m', '1h', '3600s') to seconds."""
    s = (keep_alive or "20m").strip().lower()
    try:
        if s.endswith("m"):
            return float(s[:-1]) * 60
        if s.endswith("h"):
            return float(s[:-1]) * 3600
        if s.endswith("s"):
            return float(s[:-1])
        return float(s)
    except ValueError:
        return 1200.0  # fallback: 20 minutes


class DailyLogger:
    def __init__(self, log_dir: str) -> None:
        self._log_dir = Path(_expand_path(log_dir))
        self._lock = threading.Lock()
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _path_for_today(self) -> Path:
        return self._log_dir / f"voicepaste-{datetime.now().strftime('%Y-%m-%d')}.log"

    def _fallback_path_for_today(self) -> Path:
        return self._log_dir / (
            f"voicepaste-{datetime.now().strftime('%Y-%m-%d')}-{os.getpid()}.log"
        )

    def write(self, line: str) -> None:
        payload = line.rstrip() + "\n"
        with self._lock:
            path = self._path_for_today()
            for attempt in range(5):
                try:
                    with path.open("a", encoding="utf-8") as handle:
                        handle.write(payload)
                    return
                except (PermissionError, OSError):
                    if attempt == 4:
                        break
                    time.sleep(0.25)
            try:
                with self._fallback_path_for_today().open("a", encoding="utf-8") as handle:
                    handle.write(payload)
            except (PermissionError, OSError):
                pass


@dataclass
class VoicePasteConfig:
    config_path: Path
    stt_url: str
    ollama_url: str
    clean_enabled: bool
    clean_model_local: str
    clean_model_fallback: str
    local_clean_timeout_ms: int
    cloud_clean_timeout_ms: int
    model_request_timeout_ms: int
    stt_timeout_ms: int
    paste_timeout_ms: int
    mode_default: str
    voice_paste_root: str
    journal_path: str
    journal_paste: bool
    meeting_paste: bool
    log_dir: str
    log_retention_days: int
    cloud_breaker_threshold: int
    cloud_breaker_cooldown_s: int
    stt_health_check_interval_s: int
    warmup_enabled: bool
    ollama_keep_alive: str
    app_mode: str
    model_profile: str
    fast_model: str
    quality_model: str
    fast_local_timeout_ms: int
    quality_local_timeout_ms: int
    cloud_fallback_enabled: bool
    claude_enabled: bool
    claude_api_key: str
    claude_model: str
    phrase_corrections_path: str
    hide_on_close: bool
    audio_feedback: bool
    partial_transcript_enabled: bool
    partial_update_interval_ms: int
    smart_formatting_enabled: bool
    voice_commands_enabled: bool
    meeting_session_chunk_seconds: int
    snippets_path: str
    hud_enabled: bool
    ptt_mouse_xbutton1: bool
    quit_hotkey: str

    @classmethod
    def load(cls, args: argparse.Namespace) -> "VoicePasteConfig":
        script_dir = Path(__file__).resolve().parent.parent
        config_path_arg = args.config or os.getenv("VOICEPASTE_CONFIG", "")
        config_path = (
            Path(_expand_path(config_path_arg))
            if config_path_arg
            else script_dir / defaults.DEFAULT_CONFIG_NAME
        )
        file_config: Dict[str, Any] = {}

        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                raise RuntimeError("Config root must be a JSON object.")
            file_config = payload

        def pick(name: str, cli_value: Any, default: Any) -> Any:
            if cli_value is not None:
                return cli_value
            prefixed = f"VOICEPASTE_{name}"
            if prefixed in os.environ:
                return os.environ[prefixed]
            if name in file_config:
                return file_config[name]
            return default

        legacy_model = str(
            pick("CLEAN_MODEL_LOCAL", args.clean_model_local, "")
        ).strip()
        legacy_timeout = _safe_int(
            pick(
                "LOCAL_CLEAN_TIMEOUT_MS",
                args.local_clean_timeout_ms,
                defaults.DEFAULT_LOCAL_CLEAN_TIMEOUT_MS,
            ),
            defaults.DEFAULT_LOCAL_CLEAN_TIMEOUT_MS,
            100,
        )
        fast_model = str(
            pick(
                "FAST_MODEL",
                args.fast_model,
                legacy_model or defaults.DEFAULT_FAST_MODEL,
            )
        ).strip()
        quality_model = str(
            pick("QUALITY_MODEL", args.quality_model, defaults.DEFAULT_QUALITY_MODEL)
        ).strip()
        journal_path_value = str(
            pick("JOURNAL_PATH", args.journal_path, defaults.DEFAULT_JOURNAL_PATH)
        ).strip()
        configured_voice_paste_root = str(
            pick("VOICE_PASTE_ROOT", args.voice_paste_root, "")
        ).strip()
        if configured_voice_paste_root:
            resolved_voice_paste_root = configured_voice_paste_root
        else:
            legacy_journal_dir = Path(_expand_path(journal_path_value))
            if legacy_journal_dir.suffix.lower() == ".md":
                legacy_journal_dir = legacy_journal_dir.parent
            if legacy_journal_dir.name.lower() in {"journal", "journals"}:
                resolved_voice_paste_root = str(legacy_journal_dir.parent)
            else:
                resolved_voice_paste_root = defaults.DEFAULT_VOICE_PASTE_ROOT

        cfg = cls(
            config_path=config_path,
            stt_url=str(
                pick("STT_URL", args.stt_url, defaults.DEFAULT_STT_URL)
            ).strip(),
            ollama_url=str(
                pick("OLLAMA_URL", args.ollama_url, defaults.DEFAULT_OLLAMA_URL)
            ).strip(),
            clean_enabled=_safe_bool(
                pick("CLEAN_ENABLED", args.clean, defaults.DEFAULT_CLEAN_ENABLED),
                defaults.DEFAULT_CLEAN_ENABLED,
            ),
            clean_model_local=legacy_model or fast_model,
            clean_model_fallback=str(
                pick(
                    "CLEAN_MODEL_FALLBACK",
                    args.clean_model_fallback,
                    defaults.DEFAULT_CLEAN_MODEL_FALLBACK,
                )
            ).strip(),
            local_clean_timeout_ms=legacy_timeout,
            cloud_clean_timeout_ms=_safe_int(
                pick(
                    "CLOUD_CLEAN_TIMEOUT_MS",
                    args.cloud_clean_timeout_ms,
                    defaults.DEFAULT_CLOUD_CLEAN_TIMEOUT_MS,
                ),
                defaults.DEFAULT_CLOUD_CLEAN_TIMEOUT_MS,
                200,
            ),
            model_request_timeout_ms=_safe_int(
                pick(
                    "MODEL_REQUEST_TIMEOUT_MS",
                    args.model_request_timeout_ms,
                    defaults.DEFAULT_MODEL_REQUEST_TIMEOUT_MS,
                ),
                defaults.DEFAULT_MODEL_REQUEST_TIMEOUT_MS,
                1000,
            ),
            stt_timeout_ms=_safe_int(
                pick(
                    "STT_TIMEOUT_MS",
                    args.stt_timeout_ms,
                    defaults.DEFAULT_STT_TIMEOUT_MS,
                ),
                defaults.DEFAULT_STT_TIMEOUT_MS,
                1000,
            ),
            paste_timeout_ms=_safe_int(
                pick(
                    "PASTE_TIMEOUT_MS",
                    args.paste_timeout_ms,
                    defaults.DEFAULT_PASTE_TIMEOUT_MS,
                ),
                defaults.DEFAULT_PASTE_TIMEOUT_MS,
                100,
            ),
            mode_default=str(pick("MODE_DEFAULT", args.mode, defaults.DEFAULT_MODE))
            .strip()
            .lower(),
            voice_paste_root=resolved_voice_paste_root,
            journal_path=journal_path_value,
            journal_paste=_safe_bool(
                pick(
                    "JOURNAL_PASTE", args.journal_paste, defaults.DEFAULT_JOURNAL_PASTE
                ),
                defaults.DEFAULT_JOURNAL_PASTE,
            ),
            meeting_paste=_safe_bool(
                pick(
                    "MEETING_PASTE", args.meeting_paste, defaults.DEFAULT_MEETING_PASTE
                ),
                defaults.DEFAULT_MEETING_PASTE,
            ),
            log_dir=str(
                pick("LOG_DIR", args.log_dir, defaults.DEFAULT_LOG_DIR)
            ).strip(),
            log_retention_days=_safe_int(
                pick(
                    "LOG_RETENTION_DAYS",
                    args.log_retention_days,
                    defaults.DEFAULT_LOG_RETENTION_DAYS,
                ),
                defaults.DEFAULT_LOG_RETENTION_DAYS,
                0,
            ),
            cloud_breaker_threshold=_safe_int(
                pick(
                    "CLOUD_BREAKER_THRESHOLD",
                    args.cloud_breaker_threshold,
                    defaults.DEFAULT_CLOUD_BREAKER_THRESHOLD,
                ),
                defaults.DEFAULT_CLOUD_BREAKER_THRESHOLD,
                1,
            ),
            cloud_breaker_cooldown_s=_safe_int(
                pick(
                    "CLOUD_BREAKER_COOLDOWN_S",
                    args.cloud_breaker_cooldown_s,
                    defaults.DEFAULT_CLOUD_BREAKER_COOLDOWN_S,
                ),
                defaults.DEFAULT_CLOUD_BREAKER_COOLDOWN_S,
                5,
            ),
            stt_health_check_interval_s=_safe_int(
                pick(
                    "STT_HEALTH_CHECK_INTERVAL_S",
                    args.stt_health_check_interval_s,
                    defaults.DEFAULT_STT_HEALTH_CHECK_INTERVAL_S,
                ),
                defaults.DEFAULT_STT_HEALTH_CHECK_INTERVAL_S,
                1,
            ),
            warmup_enabled=_safe_bool(
                pick(
                    "WARMUP_ENABLED",
                    args.warmup_enabled,
                    defaults.DEFAULT_WARMUP_ENABLED,
                ),
                defaults.DEFAULT_WARMUP_ENABLED,
            ),
            ollama_keep_alive=str(
                pick(
                    "OLLAMA_KEEP_ALIVE",
                    args.ollama_keep_alive,
                    defaults.DEFAULT_OLLAMA_KEEP_ALIVE,
                )
            ).strip(),
            app_mode=str(pick("APP_MODE", args.app_mode, defaults.DEFAULT_APP_MODE))
            .strip()
            .lower(),
            model_profile=str(
                pick(
                    "MODEL_PROFILE", args.model_profile, defaults.DEFAULT_MODEL_PROFILE
                )
            )
            .strip()
            .lower(),
            fast_model=fast_model,
            quality_model=quality_model,
            fast_local_timeout_ms=_safe_int(
                pick(
                    "FAST_LOCAL_TIMEOUT_MS",
                    args.fast_local_timeout_ms,
                    max(legacy_timeout, defaults.DEFAULT_FAST_LOCAL_TIMEOUT_MS),
                ),
                max(legacy_timeout, defaults.DEFAULT_FAST_LOCAL_TIMEOUT_MS),
                100,
            ),
            quality_local_timeout_ms=_safe_int(
                pick(
                    "QUALITY_LOCAL_TIMEOUT_MS",
                    args.quality_local_timeout_ms,
                    defaults.DEFAULT_QUALITY_LOCAL_TIMEOUT_MS,
                ),
                defaults.DEFAULT_QUALITY_LOCAL_TIMEOUT_MS,
                100,
            ),
            cloud_fallback_enabled=_safe_bool(
                pick(
                    "CLOUD_FALLBACK_ENABLED",
                    args.cloud_fallback_enabled,
                    defaults.DEFAULT_CLOUD_FALLBACK_ENABLED,
                ),
                defaults.DEFAULT_CLOUD_FALLBACK_ENABLED,
            ),
            claude_enabled=_safe_bool(
                pick(
                    "CLAUDE_ENABLED",
                    args.claude_enabled,
                    defaults.DEFAULT_CLAUDE_ENABLED,
                ),
                defaults.DEFAULT_CLAUDE_ENABLED,
            ),
            claude_api_key=str(
                pick("CLAUDE_API_KEY", None, os.getenv("ANTHROPIC_API_KEY", ""))
            ).strip(),
            claude_model=str(
                pick("CLAUDE_MODEL", args.claude_model, defaults.DEFAULT_CLAUDE_MODEL)
            ).strip(),
            phrase_corrections_path=str(
                pick(
                    "PHRASE_CORRECTIONS_PATH",
                    args.phrase_corrections_path,
                    defaults.DEFAULT_PHRASE_CORRECTIONS_PATH,
                )
            ).strip(),
            hide_on_close=_safe_bool(
                pick(
                    "HIDE_ON_CLOSE", args.hide_on_close, defaults.DEFAULT_HIDE_ON_CLOSE
                ),
                defaults.DEFAULT_HIDE_ON_CLOSE,
            ),
            audio_feedback=_safe_bool(
                pick(
                    "AUDIO_FEEDBACK",
                    args.audio_feedback,
                    defaults.DEFAULT_AUDIO_FEEDBACK,
                ),
                defaults.DEFAULT_AUDIO_FEEDBACK,
            ),
            partial_transcript_enabled=_safe_bool(
                pick(
                    "PARTIAL_TRANSCRIPT_ENABLED",
                    getattr(args, "partial_transcript_enabled", None),
                    defaults.DEFAULT_PARTIAL_TRANSCRIPT_ENABLED,
                ),
                defaults.DEFAULT_PARTIAL_TRANSCRIPT_ENABLED,
            ),
            partial_update_interval_ms=_safe_int(
                pick(
                    "PARTIAL_UPDATE_INTERVAL_MS",
                    getattr(args, "partial_update_interval_ms", None),
                    defaults.DEFAULT_PARTIAL_UPDATE_INTERVAL_MS,
                ),
                defaults.DEFAULT_PARTIAL_UPDATE_INTERVAL_MS,
                100,
            ),
            smart_formatting_enabled=_safe_bool(
                pick(
                    "SMART_FORMATTING_ENABLED",
                    getattr(args, "smart_formatting_enabled", None),
                    defaults.DEFAULT_SMART_FORMATTING_ENABLED,
                ),
                defaults.DEFAULT_SMART_FORMATTING_ENABLED,
            ),
            voice_commands_enabled=_safe_bool(
                pick(
                    "VOICE_COMMANDS_ENABLED",
                    getattr(args, "voice_commands_enabled", None),
                    defaults.DEFAULT_VOICE_COMMANDS_ENABLED,
                ),
                defaults.DEFAULT_VOICE_COMMANDS_ENABLED,
            ),
            meeting_session_chunk_seconds=_safe_int(
                pick(
                    "MEETING_SESSION_CHUNK_SECONDS",
                    getattr(args, "meeting_session_chunk_seconds", None),
                    defaults.DEFAULT_MEETING_SESSION_CHUNK_SECONDS,
                ),
                defaults.DEFAULT_MEETING_SESSION_CHUNK_SECONDS,
                5,
            ),
            snippets_path=str(
                pick(
                    "SNIPPETS_PATH",
                    getattr(args, "snippets_path", None),
                    defaults.DEFAULT_SNIPPETS_PATH,
                )
            ).strip(),
            hud_enabled=_safe_bool(
                pick(
                    "HUD_ENABLED",
                    getattr(args, "hud_enabled", None),
                    defaults.DEFAULT_HUD_ENABLED,
                ),
                defaults.DEFAULT_HUD_ENABLED,
            ),
            ptt_mouse_xbutton1=_safe_bool(
                pick("PTT_MOUSE_XBUTTON1", None, False),
                False,
            ),
            quit_hotkey=str(
                pick("QUIT_HOTKEY", getattr(args, "quit_hotkey", None), DEFAULT_QUIT_HOTKEY)
            ).strip().lower()
            or DEFAULT_QUIT_HOTKEY,
        )
        cfg.validate()
        return cfg

    def save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as handle:
            json.dump(self.to_json_dict(), handle, indent=2)

    def merged(self, updates: Dict[str, Any]) -> "VoicePasteConfig":
        merged = self.to_json_dict()
        merged.update(updates)
        ns = argparse.Namespace(
            config=str(self.config_path),
            stt_url=merged.get("STT_URL"),
            ollama_url=merged.get("OLLAMA_URL"),
            clean_model_local=merged.get("CLEAN_MODEL_LOCAL"),
            clean_model_fallback=merged.get("CLEAN_MODEL_FALLBACK"),
            local_clean_timeout_ms=merged.get("LOCAL_CLEAN_TIMEOUT_MS"),
            cloud_clean_timeout_ms=merged.get("CLOUD_CLEAN_TIMEOUT_MS"),
            model_request_timeout_ms=merged.get("MODEL_REQUEST_TIMEOUT_MS"),
            stt_timeout_ms=merged.get("STT_TIMEOUT_MS"),
            paste_timeout_ms=merged.get("PASTE_TIMEOUT_MS"),
            mode=merged.get("MODE_DEFAULT"),
            voice_paste_root=merged.get("VOICE_PASTE_ROOT"),
            journal_path=merged.get("JOURNAL_PATH"),
            journal_paste=merged.get("JOURNAL_PASTE"),
            meeting_paste=merged.get("MEETING_PASTE"),
            log_dir=merged.get("LOG_DIR"),
            log_retention_days=merged.get("LOG_RETENTION_DAYS"),
            cloud_breaker_threshold=merged.get("CLOUD_BREAKER_THRESHOLD"),
            cloud_breaker_cooldown_s=merged.get("CLOUD_BREAKER_COOLDOWN_S"),
            stt_health_check_interval_s=merged.get("STT_HEALTH_CHECK_INTERVAL_S"),
            warmup_enabled=merged.get("WARMUP_ENABLED"),
            ollama_keep_alive=merged.get("OLLAMA_KEEP_ALIVE"),
            clean=merged.get("CLEAN_ENABLED"),
            app_mode=merged.get("APP_MODE"),
            model_profile=merged.get("MODEL_PROFILE"),
            fast_model=merged.get("FAST_MODEL"),
            quality_model=merged.get("QUALITY_MODEL"),
            fast_local_timeout_ms=merged.get("FAST_LOCAL_TIMEOUT_MS"),
            quality_local_timeout_ms=merged.get("QUALITY_LOCAL_TIMEOUT_MS"),
            cloud_fallback_enabled=merged.get("CLOUD_FALLBACK_ENABLED"),
            claude_enabled=merged.get("CLAUDE_ENABLED"),
            claude_model=merged.get("CLAUDE_MODEL"),
            phrase_corrections_path=merged.get("PHRASE_CORRECTIONS_PATH"),
            hide_on_close=merged.get("HIDE_ON_CLOSE"),
            audio_feedback=merged.get("AUDIO_FEEDBACK"),
            partial_transcript_enabled=merged.get("PARTIAL_TRANSCRIPT_ENABLED"),
            partial_update_interval_ms=merged.get("PARTIAL_UPDATE_INTERVAL_MS"),
            smart_formatting_enabled=merged.get("SMART_FORMATTING_ENABLED"),
            voice_commands_enabled=merged.get("VOICE_COMMANDS_ENABLED"),
            meeting_session_chunk_seconds=merged.get("MEETING_SESSION_CHUNK_SECONDS"),
            snippets_path=merged.get("SNIPPETS_PATH"),
            hud_enabled=merged.get("HUD_ENABLED"),
            ptt_mouse_xbutton1=merged.get("PTT_MOUSE_XBUTTON1"),
            quit_hotkey=merged.get("QUIT_HOTKEY"),
        )
        return VoicePasteConfig.load(ns)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VoicePasteConfig":
        parser = build_parser()
        args = parser.parse_args([])
        for k, v in data.items():
            setattr(args, k.lower(), v)
        if "MODE_DEFAULT" in data:
            args.mode = data["MODE_DEFAULT"]
        if "HUD_ENABLED" in data:
            args.hud_enabled = data["HUD_ENABLED"]
        return VoicePasteConfig.load(args)

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "STT_URL": self.stt_url,
            "OLLAMA_URL": self.ollama_url,
            "CLEAN_ENABLED": self.clean_enabled,
            "CLEAN_MODEL_LOCAL": self.active_local_model,
            "CLEAN_MODEL_FALLBACK": self.clean_model_fallback,
            "LOCAL_CLEAN_TIMEOUT_MS": self.active_local_timeout_ms,
            "CLOUD_CLEAN_TIMEOUT_MS": self.cloud_clean_timeout_ms,
            "MODEL_REQUEST_TIMEOUT_MS": self.model_request_timeout_ms,
            "STT_TIMEOUT_MS": self.stt_timeout_ms,
            "PASTE_TIMEOUT_MS": self.paste_timeout_ms,
            "MODE_DEFAULT": self.mode_default,
            "VOICE_PASTE_ROOT": self.voice_paste_root,
            "JOURNAL_PATH": self.journal_path,
            "JOURNAL_PASTE": self.journal_paste,
            "MEETING_PASTE": self.meeting_paste,
            "LOG_DIR": self.log_dir,
            "LOG_RETENTION_DAYS": self.log_retention_days,
            "CLOUD_BREAKER_THRESHOLD": self.cloud_breaker_threshold,
            "CLOUD_BREAKER_COOLDOWN_S": self.cloud_breaker_cooldown_s,
            "STT_HEALTH_CHECK_INTERVAL_S": self.stt_health_check_interval_s,
            "WARMUP_ENABLED": self.warmup_enabled,
            "OLLAMA_KEEP_ALIVE": self.ollama_keep_alive,
            "APP_MODE": self.app_mode,
            "MODEL_PROFILE": self.model_profile,
            "FAST_MODEL": self.fast_model,
            "QUALITY_MODEL": self.quality_model,
            "FAST_LOCAL_TIMEOUT_MS": self.fast_local_timeout_ms,
            "QUALITY_LOCAL_TIMEOUT_MS": self.quality_local_timeout_ms,
            "CLOUD_FALLBACK_ENABLED": self.cloud_fallback_enabled,
            "CLAUDE_ENABLED": self.claude_enabled,
            "CLAUDE_MODEL": self.claude_model,
            "PHRASE_CORRECTIONS_PATH": self.phrase_corrections_path,
            "HIDE_ON_CLOSE": self.hide_on_close,
            "AUDIO_FEEDBACK": self.audio_feedback,
            "PARTIAL_TRANSCRIPT_ENABLED": self.partial_transcript_enabled,
            "PARTIAL_UPDATE_INTERVAL_MS": self.partial_update_interval_ms,
            "SMART_FORMATTING_ENABLED": self.smart_formatting_enabled,
            "VOICE_COMMANDS_ENABLED": self.voice_commands_enabled,
            "MEETING_SESSION_CHUNK_SECONDS": self.meeting_session_chunk_seconds,
            "SNIPPETS_PATH": self.snippets_path,
            "HUD_ENABLED": self.hud_enabled,
            "PTT_MOUSE_XBUTTON1": self.ptt_mouse_xbutton1,
            "QUIT_HOTKEY": self.quit_hotkey,
        }

    def validate(self) -> None:
        if not self.stt_url:
            raise ValueError("STT_URL cannot be empty.")
        if not self.ollama_url:
            raise ValueError("OLLAMA_URL cannot be empty.")
        if self.log_retention_days < 0:
            raise ValueError("LOG_RETENTION_DAYS must be >= 0.")
        if self.mode_default not in VALID_MODES:
            raise ValueError(
                "MODE_DEFAULT must be dictation, assistant, journal, or meeting."
            )
        if not self.voice_paste_root.strip():
            raise ValueError("VOICE_PASTE_ROOT cannot be empty.")
        if self.model_profile not in VALID_MODEL_PROFILES:
            raise ValueError("Model profile must be verbatim, fast, or quality.")

        if self.app_mode not in VALID_APP_MODES:
            raise ValueError("APP_MODE must be tray or cli.")
        if not self.snippets_path.strip():
            raise ValueError("SNIPPETS_PATH cannot be empty.")

    @property
    def stt_health_url(self) -> str:
        url = self.stt_url.rstrip("/")
        if url.endswith("/transcribe"):
            return url[: -len("/transcribe")] + "/health"
        return f"{url}/health"

    @property
    def ollama_generate_url(self) -> str:
        return f"{self.ollama_url.rstrip('/')}/api/generate"

    @property
    def active_local_model(self) -> str:
        if self.model_profile == "quality":
            return self.quality_model
        return self.fast_model

    @property
    def active_local_timeout_ms(self) -> int:
        if self.model_profile == "quality":
            return self.quality_local_timeout_ms
        return self.fast_local_timeout_ms

    def voice_paste_root_path(self) -> Path:
        root = Path(_expand_path(self.voice_paste_root))
        if root.suffix.lower() == ".md":
            return root.parent
        return root

    def transcript_file_path_for_mode(self, mode: str) -> Path:
        folder_map = {
            "dictation": "inbox",
            "assistant": "inbox",
            "journal": "journal",
            "meeting": "meetings",
        }
        folder = folder_map.get((mode or "").strip().lower(), "inbox")
        root = self.voice_paste_root_path()
        now = datetime.now()
        year_str = now.strftime("%Y")
        month_str = now.strftime("%m")
        date_str = now.strftime("%Y-%m-%d")
        return root / folder / year_str / month_str / f"{date_str}.md"

    def ensure_voice_paste_directories(self) -> Dict[str, Path]:
        root = self.voice_paste_root_path()
        folders = {
            "inbox": root / "inbox",
            "journal": root / "journal",
            "meetings": root / "meetings",
        }
        for path in folders.values():
            path.mkdir(parents=True, exist_ok=True)
        return folders

    def journal_file_path_for_today(self) -> Path:
        return self.transcript_file_path_for_mode("journal")

    def phrase_corrections_path_expanded(self) -> Path:
        return Path(_expand_path(self.phrase_corrections_path))

    def snippets_path_expanded(self) -> Path:
        return Path(_expand_path(self.snippets_path))

    def display(self) -> Dict[str, Any]:
        return {
            "APP_MODE": self.app_mode,
            "STT_URL": self.stt_url,
            "OLLAMA_URL": self.ollama_url,
            "CLEAN_ENABLED": self.clean_enabled,
            "MODEL_PROFILE": self.model_profile,
            "ACTIVE_LOCAL_MODEL": self.active_local_model,
            "CLEAN_MODEL_FALLBACK": self.clean_model_fallback,
            "FAST_MODEL": self.fast_model,
            "QUALITY_MODEL": self.quality_model,
            "FAST_LOCAL_TIMEOUT_MS": self.fast_local_timeout_ms,
            "QUALITY_LOCAL_TIMEOUT_MS": self.quality_local_timeout_ms,
            "CLOUD_FALLBACK_ENABLED": self.cloud_fallback_enabled,
            "CLOUD_CLEAN_TIMEOUT_MS": self.cloud_clean_timeout_ms,
            "MODE_DEFAULT": self.mode_default,
            "VOICE_PASTE_ROOT": str(self.voice_paste_root_path()),
            "VOICE_PASTE_INBOX": str(
                self.transcript_file_path_for_mode("dictation").parent
            ),
            "VOICE_PASTE_JOURNAL": str(
                self.transcript_file_path_for_mode("journal").parent
            ),
            "VOICE_PASTE_MEETINGS": str(
                self.transcript_file_path_for_mode("meeting").parent
            ),
            "JOURNAL_PATH": str(self.journal_file_path_for_today()),
            "PHRASE_CORRECTIONS_PATH": str(self.phrase_corrections_path_expanded()),
            "SNIPPETS_PATH": str(self.snippets_path_expanded()),
            "LOG_DIR": str(Path(_expand_path(self.log_dir))),
            "LOG_RETENTION_DAYS": self.log_retention_days,
            "OLLAMA_KEEP_ALIVE": self.ollama_keep_alive,
            "PARTIAL_TRANSCRIPT_ENABLED": self.partial_transcript_enabled,
            "PARTIAL_UPDATE_INTERVAL_MS": self.partial_update_interval_ms,
            "SMART_FORMATTING_ENABLED": self.smart_formatting_enabled,
            "VOICE_COMMANDS_ENABLED": self.voice_commands_enabled,
            "MEETING_SESSION_CHUNK_SECONDS": self.meeting_session_chunk_seconds,
            "PTT_MOUSE_XBUTTON1": self.ptt_mouse_xbutton1,
            "QUIT_HOTKEY": self.quit_hotkey,
        }


def _normalize_ptt_key(event: Any) -> Optional[str]:
    code = getattr(event, "scan_code", None)
    if code in PTT_KEY_SCAN_CODES:
        return PTT_KEY_SCAN_CODES[code]
    name = (getattr(event, "name", "") or "").strip().lower()
    return PTT_KEY_ALIASES.get(name)


def is_ptt_key_event(event: Any) -> bool:
    return _normalize_ptt_key(event) in (
        PTT_PRIMARY_CHORD_KEYS | PTT_FALLBACK_CHORD_KEYS
    )


def is_ptt_chord_active(keys: set[str]) -> bool:
    return (keys >= PTT_PRIMARY_CHORD_KEYS) or (keys >= PTT_FALLBACK_CHORD_KEYS)


class PushToTalkClient:
    def __init__(
        self,
        config: VoicePasteConfig,
        status_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.config = config
        self.language = os.getenv("STT_LANGUAGE", "en")
        self._status_callback = status_callback
        self._event_callback = event_callback
        self._lock = threading.Lock()
        self._config_lock = threading.RLock()
        self._fallback_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._mode_lock = threading.Lock()
        self._clipboard_lock = threading.Lock()
        self._phrase_lock = threading.Lock()
        self._snippets_lock = threading.Lock()
        self._recording = False
        self._listening_enabled = True
        self._stream = None
        self._frames: List[np.ndarray] = []
        self._target_hwnd = None
        self._record_start_monotonic = 0.0
        self._mode = config.mode_default
        self._assistant_profile = "neutral"
        self._executor = ThreadPoolExecutor(
            max_workers=8, thread_name_prefix="voicepaste"
        )
        self._last_stt_health_check = 0.0
        self._stt_available = False
        self._started_at_monotonic = time.monotonic()
        self._utterance_counter = 0
        self._current_recording_id = 0
        self._latest_utterance_id = 0
        self._cloud_failure_count = 0
        self._cloud_breaker_open_until = 0.0
        self._consecutive_fallbacks = 0  # resets on successful cleanup; triggers ERROR alert at threshold
        self._error_counts: Dict[str, int] = {
            "stt_errors": 0,
            "cleanup_errors": 0,
            "paste_failures": 0,
        }
        self._stats: Dict[str, float] = {
            "utterances_total": 0.0,
            "utterances_completed": 0.0,
            "utterances_stt_failed": 0.0,
            "utterances_empty": 0.0,
            "total_chars": 0.0,
            "sum_capture_ms": 0.0,
            "sum_stt_ms": 0.0,
            "sum_cleanup_ms": 0.0,
            "sum_total_ms": 0.0,
        }
        self._logger = DailyLogger(self.config.log_dir)
        self._hotkey_refs: List[Any] = []
        self._keyboard_hook = None
        self._hotkeys_registered = False
        self._warm_state = "cold"
        self._last_utterance_at = 0.0
        self._vram_poll_stop_event = threading.Event()
        self._vram_poll_thread: Optional[threading.Thread] = None
        self._mouse_ptt_stop_event = threading.Event()
        self._mouse_ptt_thread: Optional[threading.Thread] = None
        self._mouse_ptt_down = False
        self._last_paused_notice_at = 0.0
        self._ptt_pressed: set[str] = set()
        self._phrase_exact: List[Tuple[str, str]] = []
        self._phrase_regex: List[Tuple[re.Pattern[str], str]] = []
        self._phrase_mtime: float = 0.0
        self._snippet_pairs: List[Tuple[str, str]] = []
        self._partial_stop_event = threading.Event()
        self._partial_thread: Optional[threading.Thread] = None
        self._partial_text_by_utterance: Dict[int, str] = {}
        self._partial_stabilizers: Dict[int, PartialTranscriptStabilizer] = {}
        self._meeting_session_active = False
        self._meeting_session_id: Optional[str] = None
        self._meeting_session_stream: Any = None
        self._meeting_session_frames: List[np.ndarray] = []
        self._meeting_session_thread: Optional[threading.Thread] = None
        self._meeting_last_session_notice_at = 0.0
        self._meeting_chunk_started_at = 0.0
        self._load_phrase_corrections()
        self._load_snippets()
        try:
            threading.Thread(target=self._sync_remote_vocabulary, daemon=True).start()
        except Exception:
            pass


    def _pipeline_config_snapshot(self) -> Dict[str, Any]:
        with self._config_lock:
            cfg = self.config
            return {
                "stt_url": cfg.stt_url,
                "stt_timeout_ms": cfg.stt_timeout_ms,
                "clean_enabled": cfg.clean_enabled,
                "active_local_model": cfg.active_local_model,
                "model_request_timeout_ms": cfg.model_request_timeout_ms,
                "active_local_timeout_ms": cfg.active_local_timeout_ms,
                "clean_model_fallback": cfg.clean_model_fallback,
                "cloud_clean_timeout_ms": cfg.cloud_clean_timeout_ms,
                "cloud_fallback_enabled": cfg.cloud_fallback_enabled,
                "cloud_breaker_threshold": cfg.cloud_breaker_threshold,
                "cloud_breaker_cooldown_s": cfg.cloud_breaker_cooldown_s,
                "claude_enabled": cfg.claude_enabled,
                "claude_api_key": cfg.claude_api_key,
                "claude_model": cfg.claude_model,
                "ollama_generate_url": cfg.ollama_generate_url,
                "ollama_keep_alive": cfg.ollama_keep_alive,
                "paste_timeout_ms": cfg.paste_timeout_ms,
                "journal_paste": cfg.journal_paste,
                "meeting_paste": cfg.meeting_paste,
                "journal_file_path": str(cfg.journal_file_path_for_today()),
                "inbox_file_path": str(cfg.transcript_file_path_for_mode("dictation")),
                "meeting_file_path": str(cfg.transcript_file_path_for_mode("meeting")),
                "model_profile": cfg.model_profile,
                "audio_feedback": cfg.audio_feedback,
                "partial_transcript_enabled": cfg.partial_transcript_enabled,
                "partial_update_interval_ms": cfg.partial_update_interval_ms,
                "smart_formatting_enabled": cfg.smart_formatting_enabled,
                "voice_commands_enabled": cfg.voice_commands_enabled,
                "meeting_session_chunk_seconds": cfg.meeting_session_chunk_seconds,
            }

    def _health_config_snapshot(self) -> Dict[str, Any]:
        with self._config_lock:
            cfg = self.config
            return {
                "stt_health_url": cfg.stt_health_url,
                "stt_timeout_ms": cfg.stt_timeout_ms,
            }

    @property
    def logger_dir(self) -> Path:
        with self._config_lock:
            return Path(_expand_path(self.config.log_dir))

    def is_hud_enabled(self) -> bool:
        with self._config_lock:
            return self.config.hud_enabled

    def set_hud_enabled(self, enabled: bool) -> None:
        with self._config_lock:
            self.config.hud_enabled = enabled
            if hasattr(self, "_hud") and self._hud:
                self._hud.set_enabled(enabled)

    def _beep(self, mode: str = "ok") -> None:
        if not self.config.audio_feedback or sys.platform != "win32":
            return
        try:
            winsound.MessageBeep(
                winsound.MB_ICONEXCLAMATION if mode in ("warning", "error") else winsound.MB_OK
            )
        except Exception:
            pass

    _play_sound = _beep

    def _status(
        self, state: str, message: str, utterance_id: Optional[int] = None
    ) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[u{utterance_id}]" if utterance_id else ""
        line = f"[{stamp}][{state.upper()}]{prefix} {message}".rstrip()
        logging.getLogger("voicepaste").info(line)
        self._logger.write(line)
        if hasattr(self, "_hud") and self._hud:
            try:
                self._hud.show_status(state)
            except Exception:
                pass
        if self._status_callback:
            try:
                self._status_callback(
                    {
                        "state": state.upper(),
                        "message": message,
                        "utterance_id": utterance_id,
                        "line": line,
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    }
                )
            except Exception:
                pass

    def _event(self, payload: Dict[str, Any]) -> None:
        self._logger.write(f"EVENT {json.dumps(payload, ensure_ascii=True)}")
        if self._event_callback:
            try:
                self._event_callback(payload)
            except Exception:
                pass

    def _increment_error(self, key: str) -> None:
        with self._lock:
            if key in self._error_counts:
                self._error_counts[key] += 1

    def _on_cleanup_fallback(self, utterance_id: Optional[int] = None) -> None:
        """Track consecutive cleanup fallbacks; emit ERROR tray alert at threshold."""
        with self._lock:
            self._consecutive_fallbacks += 1
            count = self._consecutive_fallbacks
        if count >= _FALLBACK_ALERT_THRESHOLD:
            self._status(
                "ERROR",
                f"Cleanup degraded: {count} consecutive fallbacks — check Ollama at {self.config.ollama_url}",
                utterance_id,
            )

    def _is_latest_utterance(self, utterance_id: int) -> bool:
        with self._lock:
            return utterance_id == self._latest_utterance_id

    def is_listening(self) -> bool:
        with self._lock:
            return self._listening_enabled

    def get_mode(self) -> str:
        with self._mode_lock:
            return self._mode

    def is_meeting_session_active(self) -> bool:
        with self._lock:
            return self._meeting_session_active

    def get_meeting_chunk_elapsed_s(self) -> int:
        """Seconds elapsed in the current meeting chunk (0 if no session active)."""
        with self._lock:
            if (
                not self._meeting_session_active
                or self._meeting_chunk_started_at == 0.0
            ):
                return 0
        return max(0, int(time.monotonic() - self._meeting_chunk_started_at))

    def get_assistant_profile(self) -> str:
        with self._mode_lock:
            return self._assistant_profile

    def get_model_profile(self) -> str:
        with self._config_lock:
            return self.config.model_profile

    def get_active_local_model(self) -> str:
        with self._config_lock:
            return self.config.active_local_model

    def get_warm_state(self) -> str:
        return self._warm_state

    def get_hotkey_bindings(self) -> Dict[str, str]:
        return {
            "ptt": "Left Ctrl + Left Alt (fallback: Ctrl + Numpad 0)",
            "mode_dictation": MODE_HOTKEYS["dictation"],
            "mode_assistant": MODE_HOTKEYS["assistant"],
            "mode_journal": MODE_HOTKEYS["journal"],
            "mode_meeting": MODE_HOTKEYS["meeting"],
            "profile_email": PROFILE_HOTKEYS["email"],
            "profile_chat": PROFILE_HOTKEYS["chat"],
            "profile_neutral": PROFILE_HOTKEYS["neutral"],
            "model_fast": MODEL_HOTKEYS["fast"],
            "model_quality": MODEL_HOTKEYS["quality"],
        }

    def get_stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            snapshot = dict(self._stats)
        uptime_s = max(0.0, time.monotonic() - self._started_at_monotonic)
        completed = int(snapshot["utterances_completed"])
        avg_total_ms = int(snapshot["sum_total_ms"] / completed) if completed else 0
        avg_stt_ms = int(snapshot["sum_stt_ms"] / completed) if completed else 0
        avg_cleanup_ms = int(snapshot["sum_cleanup_ms"] / completed) if completed else 0
        avg_chars = int(snapshot["total_chars"] / completed) if completed else 0
        with self._lock:
            error_counts = dict(self._error_counts)
        return {
            "uptime_s": int(uptime_s),
            "utterances_total": int(snapshot["utterances_total"]),
            "utterances_completed": completed,
            "utterances_stt_failed": int(snapshot["utterances_stt_failed"]),
            "utterances_empty": int(snapshot["utterances_empty"]),
            "avg_total_ms": avg_total_ms,
            "avg_stt_ms": avg_stt_ms,
            "avg_cleanup_ms": avg_cleanup_ms,
            "avg_chars": avg_chars,
            "error_counts": error_counts,
        }

    def _record_stats(self, event: Dict[str, Any]) -> None:
        timings = event.get("timings_ms", {})
        with self._stats_lock:
            self._stats["utterances_total"] += 1
            self._stats["sum_capture_ms"] += float(timings.get("capture", 0) or 0)
            self._stats["sum_stt_ms"] += float(timings.get("stt", 0) or 0)
            self._stats["sum_cleanup_ms"] += float(timings.get("cleanup", 0) or 0)
            self._stats["sum_total_ms"] += float(timings.get("total", 0) or 0)
            result = str(event.get("paste_result", ""))
            if result in {"stt_failed", "meeting_chunk_failed_saved"}:
                self._stats["utterances_stt_failed"] += 1
            elif result == "empty":
                self._stats["utterances_empty"] += 1
            else:
                self._stats["utterances_completed"] += 1
                self._stats["total_chars"] += float(
                    len(str(event.get("text_cleaned", "")))
                )

    def _set_mode(self, mode: str, announce: bool = True) -> None:
        if mode not in VALID_MODES:
            return
        with self._mode_lock:
            self._mode = mode
        with self._config_lock:
            self.config.mode_default = mode
        if announce:
            self._beep("ok")
            self._status("MODE", f"Mode switched to {mode}.")

    def set_mode(self, mode: str, announce: bool = True, persist: bool = False) -> None:
        self._set_mode(mode, announce=announce)
        if persist:
            self.persist_config()

    def _set_profile(self, profile: str, announce: bool = True) -> None:
        if profile not in VALID_PROFILES:
            return
        with self._mode_lock:
            self._assistant_profile = profile
        if announce:
            self._beep("ok")
            self._status("MODE", f"Assistant profile switched to {profile}.")

    def set_assistant_profile(self, profile: str, announce: bool = True) -> None:
        self._set_profile(profile, announce=announce)

    def set_model_profile(
        self,
        profile: str,
        announce: bool = True,
        warm: bool = True,
        persist: bool = True,
    ) -> None:
        profile = (profile or "").strip().lower()
        if profile not in VALID_MODEL_PROFILES:
            raise ValueError("Model profile must be verbatim, fast, or quality.")

        with self._config_lock:
            if profile == self.config.model_profile:
                return
            self.config.model_profile = profile
            active_local_model = self.config.active_local_model
        if announce:
            self._beep("ok")
            self._status(
                "MODEL", f"Model profile switched to {profile} ({active_local_model})."
            )
        if persist:
            self.persist_config()
        if warm:
            self.warm_selected_model_now(background=True)

    def get_cloud_fallback_enabled(self) -> bool:
        with self._config_lock:
            return bool(self.config.cloud_fallback_enabled)

    def set_cloud_fallback_enabled(
        self, enabled: bool, announce: bool = True, persist: bool = True
    ) -> None:
        with self._config_lock:
            if self.config.cloud_fallback_enabled == enabled:
                return
            self.config.cloud_fallback_enabled = enabled
        if announce:
            self._beep("ok")
            label = "Cloud Gemini Free Tier" if enabled else "Local Whisper (Port 8770)"
            self._status("MODEL", f"STT Provider switched to {label}.")
        if persist:
            self.persist_config()

    def start_listening(self, announce: bool = True) -> None:
        with self._lock:
            self._listening_enabled = True
        if announce:
            self._status("IDLE", "Listening enabled.")

    def stop_listening(self, announce: bool = True) -> None:
        with self._lock:
            self._listening_enabled = False
            recording = self._recording
        if recording:
            self.stop_recording()
        if announce:
            self._status("IDLE", "Listening paused.")

    def update_runtime_config(
        self, updates: Dict[str, Any], persist: bool = True
    ) -> None:
        with self._config_lock:
            self.config = self.config.merged(updates)
            mode_default = self.config.mode_default
            log_dir = self.config.log_dir
        self._logger = DailyLogger(log_dir)
        self._load_phrase_corrections()
        self._load_snippets()
        # MODE_DEFAULT is intentionally NOT applied here — settings saves must not
        # clobber the user's current running mode. Mode only changes via set_mode()
        # (hotkey, tray menu) or on startup.
        if persist:
            self.persist_config()
        self._status("CONFIG", "Runtime settings updated.")

    def persist_config(self) -> None:
        with self._config_lock:
            self.config.save()

    def _get_mode_and_profile(self) -> Tuple[str, str]:
        with self._mode_lock:
            return self._mode, self._assistant_profile

    def register_mode_hotkeys(self) -> None:
        if self._hotkeys_registered:
            return
        self._hotkey_refs.append(
            keyboard.add_hotkey(
                MODE_HOTKEYS["dictation"], lambda: self.set_mode("dictation", persist=True)
            )
        )
        self._hotkey_refs.append(
            keyboard.add_hotkey(
                MODE_HOTKEYS["assistant"], lambda: self.set_mode("assistant", persist=True)
            )
        )
        self._hotkey_refs.append(
            keyboard.add_hotkey(
                MODE_HOTKEYS["journal"], lambda: self.set_mode("journal", persist=True)
            )
        )
        self._hotkey_refs.append(
            keyboard.add_hotkey(
                MODE_HOTKEYS["meeting"], lambda: self.set_mode("meeting", persist=True)
            )
        )
        self._hotkey_refs.append(
            keyboard.add_hotkey(
                PROFILE_HOTKEYS["neutral"], lambda: self._set_profile("neutral")
            )
        )
        self._hotkey_refs.append(
            keyboard.add_hotkey(
                PROFILE_HOTKEYS["email"], lambda: self._set_profile("email")
            )
        )
        self._hotkey_refs.append(
            keyboard.add_hotkey(
                PROFILE_HOTKEYS["chat"], lambda: self._set_profile("chat")
            )
        )
        self._hotkey_refs.append(
            keyboard.add_hotkey(
                MODEL_HOTKEYS["fast"], lambda: self.set_model_profile("fast")
            )
        )
        self._hotkey_refs.append(
            keyboard.add_hotkey(
                MODEL_HOTKEYS["quality"], lambda: self.set_model_profile("quality")
            )
        )
        self._hotkeys_registered = True

    def install_keyboard_hooks(self) -> None:
        self.register_mode_hotkeys()
        if self._keyboard_hook is None:
            self._keyboard_hook = keyboard.hook(self.on_key_event)
        if os.name == "nt":
            with self._config_lock:
                enable_mouse_ptt = self.config.ptt_mouse_xbutton1
            if enable_mouse_ptt and self._mouse_ptt_thread is None:
                self._mouse_ptt_stop_event.clear()
                self._mouse_ptt_thread = threading.Thread(
                    target=self._mouse_ptt_worker, daemon=True
                )
                self._mouse_ptt_thread.start()

    def ensure_keyboard_hooks(self) -> None:
        """Verify that keyboard hooks are active when listening.

        If the keyboard hook thread was unhooked or dropped due to a Windows OS
        exception, re-install the hook automatically.
        """
        if self.is_listening() and (self._keyboard_hook is None or not self._hotkeys_registered):
            try:
                self.install_keyboard_hooks()
                self._status("HOOKS", "Re-installed keyboard hooks automatically.")
            except Exception as exc:
                self._status("ERROR", f"Failed auto-recovery of keyboard hooks: {exc}")

    def uninstall_keyboard_hooks(self) -> None:
        if self._keyboard_hook is not None:
            try:
                keyboard.unhook(self._keyboard_hook)
            except Exception:
                pass
            self._keyboard_hook = None
        for hotkey in self._hotkey_refs:
            try:
                keyboard.remove_hotkey(hotkey)
            except Exception:
                pass
        self._hotkey_refs = []
        self._hotkeys_registered = False
        self._ptt_pressed.clear()
        self._mouse_ptt_stop_event.set()
        if self._mouse_ptt_thread is not None:
            self._mouse_ptt_thread.join(timeout=1.0)
            self._mouse_ptt_thread = None
        self._mouse_ptt_down = False

    def on_key_event(self, event: Any) -> None:
        if not is_ptt_key_event(event):
            return
        if self.is_meeting_session_active():
            now = time.monotonic()
            if (now - self._meeting_last_session_notice_at) > 2.0:
                self._meeting_last_session_notice_at = now
                self._status(
                    "MEETING",
                    "Meeting session active. Stop session to use push-to-talk.",
                )
            return
        key = _normalize_ptt_key(event)
        if key is None:
            return
        if event.event_type == "down":
            self._ptt_pressed.add(key)
            if is_ptt_chord_active(self._ptt_pressed):
                self._on_ptt_pressed()
        elif event.event_type == "up":
            self._ptt_pressed.discard(key)
            self._on_ptt_released()

    def _on_ptt_pressed(self) -> None:
        if self.is_listening():
            # Idle re-warm: if the model may have been evicted from VRAM,
            # trigger a background warmup before the user starts speaking.
            # Two triggers:
            #   1. warm + idle past ~85% of keep_alive — pre-empt the eviction
            #      timeout that Ollama itself applies.
            #   2. cold/error — the VRAM poll (or a previous warmup failure)
            #      says the model isn't loaded. Shared-Ollama setups (e.g. a
            #      second agent using a different model on the same host)
            #      routinely evict us, and until now there was no auto-recovery
            #      from cold state, so every utterance paid a full cold-start.
            if self._warm_state == "warm" and self._last_utterance_at > 0.0:
                idle_s = time.monotonic() - self._last_utterance_at
                with self._config_lock:
                    keep_alive_s = _parse_keep_alive_s(self.config.ollama_keep_alive)
                if idle_s >= keep_alive_s * 0.85:
                    self._status(
                        "WARMUP",
                        f"Idle for {int(idle_s)}s; re-warming model in background.",
                    )
                    self.warm_selected_model_now(background=True)
            elif self._warm_state in ("cold", "error"):
                with self._config_lock:
                    clean_enabled = self.config.clean_enabled
                    warmup_enabled = self.config.warmup_enabled
                if clean_enabled and warmup_enabled:
                    self._status(
                        "WARMUP",
                        f"Model {self._warm_state}; re-warming in background.",
                    )
                    self.warm_selected_model_now(background=True)
            self.start_recording()
        else:
            now = time.monotonic()
            if (now - self._last_paused_notice_at) > 2.0:
                self._last_paused_notice_at = now
                self._beep("warning")
                self._status(
                    "IDLE",
                    "Listening is paused. Use tray menu: Start Listening.",
                )

    def _on_ptt_released(self) -> None:
        if self._recording:
            self.stop_recording()

    def _is_mouse_xbutton1_down(self) -> bool:
        if os.name != "nt":
            return False
        with self._config_lock:
            enabled = self.config.ptt_mouse_xbutton1
        if not enabled:
            return False
        return bool(USER32.GetAsyncKeyState(0x05) & 0x8000)

    def _mouse_ptt_worker(self) -> None:
        while not self._mouse_ptt_stop_event.wait(timeout=0.015):
            down = self._is_mouse_xbutton1_down()
            if down and not self._mouse_ptt_down:
                self._mouse_ptt_down = True
                if self.is_meeting_session_active():
                    now = time.monotonic()
                    if (now - self._meeting_last_session_notice_at) > 2.0:
                        self._meeting_last_session_notice_at = now
                        self._status(
                            "MEETING",
                            "Meeting session active. Stop session to use push-to-talk.",
                        )
                else:
                    self._on_ptt_pressed()
            elif (not down) and self._mouse_ptt_down:
                self._mouse_ptt_down = False
                self._on_ptt_released()

    def _copy_to_clipboard(self, text: str) -> None:
        with self._clipboard_lock:
            pyperclip.copy(text)

    def _check_stt_health(self, force: bool = False) -> bool:
        health_cfg = self._health_config_snapshot()
        with self._config_lock:
            interval = self.config.stt_health_check_interval_s
        now = time.monotonic()
        if (not force) and ((now - self._last_stt_health_check) < interval):
            return self._stt_available

        ok = stt_check_health(
            health_cfg["stt_health_url"], health_cfg["stt_timeout_ms"]
        )

        previous = self._stt_available
        self._stt_available = ok
        self._last_stt_health_check = now
        if ok and not previous:
            self._status("STATUS", "STT service is now reachable.")
        if (not ok) and previous:
            self._status(
                "STATUS", "STT service became unavailable. Running in degraded mode."
            )
        # Always emit HEALTH after a real check so the tray icon stays in sync.
        self._status("HEALTH", "online" if ok else "offline")
        return ok

    def _audio_callback(
        self, indata: np.ndarray, _frames: int, _time_info: Any, status: Any
    ) -> None:
        if status:
            self._status("AUDIO", f"Input warning: {status}")
        with self._lock:
            if self._recording:
                self._frames.append(indata.copy())

    def start_recording(self) -> None:
        target_hwnd = USER32.GetForegroundWindow()
        with self._lock:
            if self._meeting_session_active:
                self._status(
                    "MEETING",
                    "Cannot start push-to-talk while meeting session is active.",
                )
                return
            if self._recording:
                return
            self._frames = []
            self._recording = True
            self._target_hwnd = target_hwnd
            self._record_start_monotonic = time.perf_counter()
            self._current_recording_id = self._utterance_counter + 1
            self._partial_stabilizers[self._current_recording_id] = (
                PartialTranscriptStabilizer(hold_back_words=2)
            )
            self._partial_stop_event.clear()
            try:
                self._stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype=DTYPE,
                    callback=self._audio_callback,
                    blocksize=4096,
                    device=None,
                )
                self._stream.start()
            except Exception as exc:
                self._recording = False
                self._stream = None
                self._status("ERROR", f"Unable to start recording: {exc}")
                return
        self._status("LISTENING", "Recording...")
        pipeline_cfg = self._pipeline_config_snapshot()
        if pipeline_cfg["partial_transcript_enabled"]:
            self._partial_thread = threading.Thread(
                target=self._partial_transcript_worker, daemon=True
            )
            self._partial_thread.start()

    def stop_recording(self) -> None:
        self._partial_stop_event.set()
        with self._lock:
            if not self._recording:
                return
            self._recording = False
            stream = self._stream
            frames = self._frames
            target_hwnd = self._target_hwnd
            capture_started_at = self._record_start_monotonic
            self._stream = None
            self._frames = []
            self._target_hwnd = None
            self._record_start_monotonic = 0.0
            utterance_id = self._current_recording_id or (self._utterance_counter + 1)
            self._utterance_counter = max(self._utterance_counter, utterance_id)
            self._current_recording_id = 0
            self._latest_utterance_id = utterance_id
            partial_text = self._partial_text_by_utterance.pop(utterance_id, "")
            self._partial_stabilizers.pop(utterance_id, None)

        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:
                self._status("AUDIO", f"Stream close warning: {exc}", utterance_id)
        if self._partial_thread is not None:
            self._partial_thread.join(timeout=1.0)
            self._partial_thread = None

        self._last_utterance_at = time.monotonic()

        if not frames:
            self._status("STATUS", "No audio captured.", utterance_id)
            return

        audio = np.concatenate(frames, axis=0)

        # Safe trailing padding: keep full audio buffer so trailing words are never clipped
        pass

        # Guard: Whisper hallucinates badly on very short clips (<300 ms)
        min_samples = int(SAMPLE_RATE * 0.3)  # 300 ms minimum
        if audio.shape[0] < min_samples:
            self._status("STATUS", "Recording too short (<300 ms), ignoring.", utterance_id)
            return

        wav_bytes = self._to_wav_bytes(audio)
        mode, profile = self._get_mode_and_profile()
        pipeline_cfg = self._pipeline_config_snapshot()
        capture_ms = (
            int((time.perf_counter() - capture_started_at) * 1000)
            if capture_started_at > 0
            else 0
        )
        threading.Thread(
            target=self._process_utterance,
            args=(
                utterance_id,
                wav_bytes,
                target_hwnd,
                capture_ms,
                mode,
                profile,
                pipeline_cfg,
                None,
                partial_text,
            ),
            daemon=True,
        ).start()

    def _partial_transcript_worker(self) -> None:
        last_text = ""
        while not self._partial_stop_event.is_set():
            pipeline_cfg = self._pipeline_config_snapshot()
            interval_s = max(0.2, pipeline_cfg["partial_update_interval_ms"] / 1000.0)
            time.sleep(interval_s)
            with self._lock:
                if not self._recording:
                    break
                utterance_id = self._current_recording_id
                frames = list(self._frames)
                stabilizer = self._partial_stabilizers.get(utterance_id)
            if (not utterance_id) or (not frames):
                continue
            try:
                audio = np.concatenate(frames, axis=0)
            except Exception:
                continue
            if audio.size < (SAMPLE_RATE // 2):
                continue
            if audio.shape[0] > (SAMPLE_RATE * 12):
                audio = audio[-(SAMPLE_RATE * 12) :]
            wav_bytes = self._to_wav_bytes(audio)
            text, _ = self._transcribe_partial(wav_bytes, pipeline_cfg)
            if (not text) or text == last_text:
                continue
            last_text = text
            if stabilizer is None:
                stabilizer = PartialTranscriptStabilizer(hold_back_words=2)
                with self._lock:
                    self._partial_stabilizers[utterance_id] = stabilizer
            stable_text, _ = stabilizer.ingest(text)
            if not stable_text:
                continue
            self._partial_text_by_utterance[utterance_id] = stable_text
            self._status("LIVE", stable_text[:96], utterance_id)

    def _transcribe_partial(
        self, wav_bytes: bytes, pipeline_cfg: Dict[str, Any]
    ) -> Tuple[str, int]:
        # Keep partial prompt minimal to prevent hallucinations on sub-second audio slices
        partial_prompt = "Ade, NucBox, VoicePaste."
        partial_text, partial_ms, error = transcribe_audio_stream_partial(
            stt_url=pipeline_cfg["stt_url"],
            stt_timeout_ms=pipeline_cfg["stt_timeout_ms"],
            language=self.language,
            wav_bytes=wav_bytes,
            initial_prompt=partial_prompt,
        )
        if (not error) and partial_text:
            return partial_text.strip(), partial_ms

        raw_text, stt_ms, fallback_error = transcribe_audio(
            stt_url=pipeline_cfg["stt_url"],
            stt_timeout_ms=pipeline_cfg["stt_timeout_ms"],
            language=self.language,
            wav_bytes=wav_bytes,
            initial_prompt=partial_prompt,
        )
        if fallback_error or not raw_text:
            return "", partial_ms + stt_ms
        return raw_text.strip(), partial_ms + stt_ms

    def _meeting_audio_callback(
        self, indata: np.ndarray, _frames: int, _time_info: Any, status: Any
    ) -> None:
        if status:
            self._status("AUDIO", f"Meeting input warning: {status}")
        with self._lock:
            if self._meeting_session_active:
                self._meeting_session_frames.append(indata.copy())

    def start_meeting_session(self, announce: bool = True) -> None:
        with self._lock:
            if self._meeting_session_active:
                return
            if self._recording:
                self._status(
                    "MEETING",
                    "Stop push-to-talk recording before starting a meeting session.",
                )
                return
            self._meeting_session_active = True
            self._meeting_session_id = (
                datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
            )
            session_id = self._meeting_session_id
            self._meeting_session_frames = []
            self._meeting_chunk_started_at = time.monotonic()
            try:
                self._meeting_session_stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype=DTYPE,
                    callback=self._meeting_audio_callback,
                    blocksize=4096,
                    device=None,
                )
                self._meeting_session_stream.start()
            except Exception as exc:
                self._meeting_session_active = False
                self._meeting_session_id = None
                self._meeting_session_stream = None
                self._status("ERROR", f"Unable to start meeting session: {exc}")
                return
            self._meeting_session_thread = threading.Thread(
                target=self._meeting_session_worker, daemon=True
            )
            self._meeting_session_thread.start()

        pipeline_cfg = self._pipeline_config_snapshot()
        start_line = f"[Meeting session started: {session_id}]"
        self._append_to_transcript_file(start_line, pipeline_cfg["meeting_file_path"])
        self.set_mode("meeting", announce=False, persist=True)
        if announce:
            self._status("MEETING", f"Meeting session started ({session_id}).")

    def _wait_for_silence_before_chunk(
        self,
        hold_window_s: float = 0.35,
        max_hold_s: float = 1.0,
        energy_threshold: float = 400.0,
    ) -> None:
        """Hold the chunk boundary open until a silence window is detected."""
        def _get_frames() -> List[np.ndarray]:
            with self._lock:
                return list(self._meeting_session_frames) if self._meeting_session_active else []

        def _is_active() -> bool:
            with self._lock:
                return self._meeting_session_active

        wait_for_silence(
            get_audio_frames=_get_frames,
            is_active=_is_active,
            sample_rate=SAMPLE_RATE,
            hold_window_s=hold_window_s,
            max_hold_s=max_hold_s,
            energy_threshold=energy_threshold,
        )

    def _meeting_session_worker(self) -> None:
        while True:
            with self._lock:
                if not self._meeting_session_active:
                    break
                session_id = self._meeting_session_id or ""
            pipeline_cfg = self._pipeline_config_snapshot()
            sleep_s = max(5, int(pipeline_cfg["meeting_session_chunk_seconds"]))
            time.sleep(sleep_s)
            # Energy-based VAD hold: don't cut mid-word — wait for a natural pause
            # before flushing.  Adds at most 1 s of latency per chunk boundary.
            self._wait_for_silence_before_chunk()
            self._flush_meeting_session_chunk(session_id, final=False)

    def _flush_meeting_session_chunk(self, session_id: str, final: bool) -> None:
        with self._lock:
            frames = self._meeting_session_frames
            self._meeting_session_frames = []
            if not final:
                self._meeting_chunk_started_at = time.monotonic()
        if not frames:
            return
        try:
            audio = np.concatenate(frames, axis=0)
        except Exception:
            return
        if audio.size < (SAMPLE_RATE // 3):
            return
        capture_ms = int((audio.shape[0] / float(SAMPLE_RATE)) * 1000.0)
        wav_bytes = self._to_wav_bytes(audio)
        with self._lock:
            self._utterance_counter += 1
            utterance_id = self._utterance_counter
            self._latest_utterance_id = utterance_id
        pipeline_cfg = self._pipeline_config_snapshot()
        threading.Thread(
            target=self._process_utterance,
            args=(
                utterance_id,
                wav_bytes,
                None,
                capture_ms,
                "meeting",
                self.get_assistant_profile(),
                pipeline_cfg,
                session_id,
                "",
            ),
            daemon=True,
        ).start()
        if final:
            self._status("MEETING", "Final meeting chunk queued.", utterance_id)

    def stop_meeting_session(self, announce: bool = True) -> None:
        with self._lock:
            if not self._meeting_session_active:
                return
            session_id = self._meeting_session_id or ""
            self._meeting_session_active = False
            stream = self._meeting_session_stream
            self._meeting_session_stream = None
            thread = self._meeting_session_thread
            self._meeting_session_thread = None
            self._meeting_session_id = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        if thread is not None:
            thread.join(timeout=1.0)
        self._flush_meeting_session_chunk(session_id, final=True)
        pipeline_cfg = self._pipeline_config_snapshot()
        end_line = f"[Meeting session ended: {session_id}]"
        self._append_to_transcript_file(end_line, pipeline_cfg["meeting_file_path"])
        if announce:
            self._status("MEETING", f"Meeting session stopped ({session_id}).")

    def _to_wav_bytes(self, audio: np.ndarray) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
        return buffer.getvalue()

    def _strict_cleanup_prompt(self, raw_text: str) -> str:
        return strict_cleanup_prompt(raw_text)

    def _build_cleanup_prompt(self, raw_text: str, model_profile: str) -> Optional[str]:
        """Select prompt based on active model profile. Returns None for verbatim (skip LLM)."""
        if model_profile == "verbatim":
            return None
        if model_profile == "quality":
            return quality_cleanup_prompt(raw_text)
        return strict_cleanup_prompt(raw_text)

    def _assistant_prompt(self, text: str, profile: str) -> str:
        return build_assistant_prompt(text, profile)

    def _sanitize_model_output(self, text: str) -> str:
        return sanitize_model_output(text)

    def _call_ollama_generate(
        self,
        model: str,
        prompt: str,
        timeout_ms: int,
        num_predict: int = 160,
        pipeline_cfg: Optional[Dict[str, Any]] = None,
    ) -> str:
        cfg = pipeline_cfg or self._pipeline_config_snapshot()
        return call_ollama_generate(
            cfg["ollama_generate_url"],
            cfg["ollama_keep_alive"],
            model,
            prompt,
            timeout_ms,
            num_predict=num_predict,
        )

    def _call_claude_generate(
        self,
        prompt: str,
        timeout_ms: int,
        pipeline_cfg: Optional[Dict[str, Any]] = None,
    ) -> str:
        cfg = pipeline_cfg or self._pipeline_config_snapshot()
        return call_claude_generate(
            cfg["claude_api_key"],
            cfg["claude_model"],
            prompt,
            timeout_ms,
        )

    def _cloud_fallback_allowed(self, mode: str, pipeline_cfg: Dict[str, Any]) -> bool:
        if not pipeline_cfg["cloud_fallback_enabled"]:
            return False
        if mode == "dictation":
            return False
        with self._fallback_lock:
            return time.monotonic() >= self._cloud_breaker_open_until

    def _cloud_failure(self, pipeline_cfg: Dict[str, Any]) -> None:
        with self._fallback_lock:
            self._cloud_failure_count += 1
            if self._cloud_failure_count >= pipeline_cfg["cloud_breaker_threshold"]:
                cooldown = pipeline_cfg["cloud_breaker_cooldown_s"]
                self._cloud_breaker_open_until = time.monotonic() + cooldown
                self._cloud_failure_count = 0
            else:
                cooldown = 0
        if cooldown:
            self._status("FALLBACK", f"Cloud fallback paused for {cooldown}s.")

    def _cloud_success(self) -> None:
        with self._fallback_lock:
            self._cloud_failure_count = 0
            self._cloud_breaker_open_until = 0.0

    def _try_cloud_cleanup(
        self,
        prompt: str,
        utterance_id: int,
        mode: str,
        pipeline_cfg: Dict[str, Any],
        background: bool = False,
    ) -> Tuple[Optional[str], bool, str]:
        if not self._cloud_fallback_allowed(mode, pipeline_cfg):
            return None, False, "none"

        try:
            cleaned = self._call_ollama_generate(
                pipeline_cfg["clean_model_fallback"],
                prompt,
                pipeline_cfg["cloud_clean_timeout_ms"],
                pipeline_cfg=pipeline_cfg,
            )
            if cleaned:
                self._cloud_success()
                self._status(
                    "FALLBACK",
                    "Late cloud refinement succeeded."
                    if background
                    else "Cloud fallback used.",
                    utterance_id,
                )
                return cleaned, True, "ollama_cloud"
            self._cloud_failure(pipeline_cfg)
            return None, False, "none"
        except Exception as exc:
            self._status(
                "FALLBACK", f"Ollama cloud fallback failed: {exc}", utterance_id
            )

        if pipeline_cfg["claude_enabled"] and mode == "assistant":
            try:
                cleaned = self._call_claude_generate(
                    prompt,
                    pipeline_cfg["cloud_clean_timeout_ms"],
                    pipeline_cfg=pipeline_cfg,
                )
                if cleaned:
                    self._cloud_success()
                    self._status("FALLBACK", "Claude fallback used.", utterance_id)
                    return cleaned, True, "claude"
            except Exception as exc:
                self._status("FALLBACK", f"Claude fallback failed: {exc}", utterance_id)

        self._cloud_failure(pipeline_cfg)
        self._increment_error("cleanup_errors")
        return None, False, "none"

    def _late_refine_after_timeout(
        self,
        local_future: Future,
        prompt: str,
        utterance_id: int,
        mode: str,
        pipeline_cfg: Dict[str, Any],
        original_hwnd: Any = None,
        raw_text: str = "",
    ) -> None:
        cleaned = ""
        try:
            cleaned = (local_future.result() or "").strip()
        except Exception:
            cleaned = ""

        used_fallback = False
        route = "local"
        if not cleaned:
            fallback_text, used_fallback, route = self._try_cloud_cleanup(
                prompt,
                utterance_id,
                mode=mode,
                pipeline_cfg=pipeline_cfg,
                background=True,
            )
            cleaned = fallback_text or ""

        if (not cleaned) or (not self._is_latest_utterance(utterance_id)):
            return

        # Truncation guard: if the model returned significantly less text than it received,
        # the output was likely cut off by num_predict — fall back to raw rather than paste
        # a partial clean. Threshold: output must be at least 70% of input word count.
        if raw_text:
            input_words = len(raw_text.split())
            output_words = len(cleaned.split())
            if input_words > 20 and output_words < input_words * 0.70:
                self._status(
                    "REFINE",
                    f"Late refinement discarded — output too short "
                    f"({output_words} words vs {input_words} input). Raw text retained.",
                    utterance_id,
                )
                return

        # Safety check: has the user moved to a different window since the original paste?
        current_hwnd = USER32.GetForegroundWindow()
        window_changed = original_hwnd and (current_hwnd != original_hwnd)

        try:
            self._copy_to_clipboard(cleaned)
            if window_changed:
                # Don't silently overwrite a different application — just notify
                self._status(
                    "REFINE",
                    "Refined text ready on clipboard (window changed — paste manually).",
                    utterance_id,
                )
            else:
                message = (
                    f"Improved text copied ({route})."
                    if used_fallback
                    else "Improved local refinement copied to clipboard."
                )
                self._status("REFINE", message, utterance_id)
        except Exception as exc:
            self._increment_error("cleanup_errors")
            self._status("REFINE", f"Late refinement copy failed: {exc}", utterance_id)

    def _clean_dictation_latency_first(
        self,
        raw_text: str,
        utterance_id: int,
        pipeline_cfg: Dict[str, Any],
        target_hwnd: Any = None,
    ) -> Tuple[str, bool, int, str]:
        if not pipeline_cfg["clean_enabled"]:
            return raw_text, False, 0, "none"

        model_profile = pipeline_cfg["model_profile"]
        prompt = self._build_cleanup_prompt(raw_text, model_profile)
        if prompt is None:
            return raw_text, False, 0, "verbatim"

        # Quality mode: block until cleanup completes so the paste fires only once,
        # with the quality-cleaned text.  The latency-first approach (paste raw
        # immediately, refine in background) breaks quality mode because the timeout
        # fires before the slower model finishes, raw text gets pasted, and the
        # quality result is then silently dropped onto the clipboard without a paste.
        if model_profile == "quality":
            cleaned, used_fallback, cleanup_ms, route = self._clean_blocking_with_fallback(
                prompt,
                utterance_id,
                pipeline_cfg["active_local_timeout_ms"],
                mode="dictation",
                pipeline_cfg=pipeline_cfg,
            )
            if not cleaned:
                self._status(
                    "FALLBACK", "Cleanup failed — pasting raw transcript", utterance_id
                )
                self._on_cleanup_fallback(utterance_id)
            return (cleaned or raw_text), used_fallback, cleanup_ms, route

        num_predict = 160
        started = time.perf_counter()
        local_future = self._executor.submit(
            self._call_ollama_generate,
            pipeline_cfg["active_local_model"],
            prompt,
            pipeline_cfg["model_request_timeout_ms"],
            num_predict,
            pipeline_cfg,
        )

        try:
            cleaned = local_future.result(
                timeout=pipeline_cfg["active_local_timeout_ms"] / 1000.0
            )
            cleanup_ms = int((time.perf_counter() - started) * 1000)
            if cleaned:
                return cleaned, False, cleanup_ms, "local"
        except FutureTimeoutError:
            cleanup_ms = int((time.perf_counter() - started) * 1000)
            self._status(
                "CLEANING",
                "Local cleanup timed out; raw text pasted immediately.",
                utterance_id,
            )
            self._executor.submit(
                self._late_refine_after_timeout,
                local_future,
                prompt,
                utterance_id,
                "dictation",
                pipeline_cfg,
                target_hwnd,
                raw_text,
            )
            return raw_text, False, cleanup_ms, "none"
        except Exception as exc:
            self._status("CLEANING", f"Local cleanup failed: {exc}", utterance_id)
            logging.getLogger("voicepaste").error("Cleanup exception", exc_info=exc)
            self._increment_error("cleanup_errors")

        cleanup_ms = int((time.perf_counter() - started) * 1000)
        self._status("FALLBACK", "Cleanup failed — pasting raw transcript", utterance_id)
        self._on_cleanup_fallback(utterance_id)
        return raw_text, False, cleanup_ms, "none"

    def _clean_blocking_with_fallback(
        self,
        prompt: str,
        utterance_id: int,
        local_timeout_ms: int,
        mode: str,
        pipeline_cfg: Dict[str, Any],
    ) -> Tuple[Optional[str], bool, int, str]:
        started = time.perf_counter()
        try:
            cleaned = self._call_ollama_generate(
                pipeline_cfg["active_local_model"],
                prompt,
                local_timeout_ms,
                pipeline_cfg=pipeline_cfg,
            )
            if cleaned:
                return (
                    cleaned,
                    False,
                    int((time.perf_counter() - started) * 1000),
                    "local",
                )
        except Exception as exc:
            self._increment_error("cleanup_errors")
            self._status("CLEANING", f"Local cleanup failed: {exc}", utterance_id)

        fallback_text, used_fallback, route = self._try_cloud_cleanup(
            prompt,
            utterance_id,
            mode=mode,
            pipeline_cfg=pipeline_cfg,
            background=False,
        )
        return (
            fallback_text,
            used_fallback,
            int((time.perf_counter() - started) * 1000),
            route,
        )

    def _clean_for_journal(
        self, raw_text: str, utterance_id: int, pipeline_cfg: Dict[str, Any]
    ) -> Tuple[str, bool, int, str]:
        if not pipeline_cfg["clean_enabled"]:
            return raw_text, False, 0, "none"
        prompt = self._build_cleanup_prompt(raw_text, pipeline_cfg["model_profile"])
        if prompt is None:
            return raw_text, False, 0, "verbatim"
        cleaned, used_fallback, cleanup_ms, route = self._clean_blocking_with_fallback(
            prompt,
            utterance_id,
            max(pipeline_cfg["active_local_timeout_ms"] * 2, 2500),
            mode="journal",
            pipeline_cfg=pipeline_cfg,
        )
        if not cleaned:
            self._status("FALLBACK", "Cleanup failed — pasting raw transcript", utterance_id)
            self._on_cleanup_fallback(utterance_id)
        return (cleaned or raw_text), used_fallback, cleanup_ms, route

    def _clean_for_assistant(
        self,
        raw_text: str,
        utterance_id: int,
        profile: str,
        pipeline_cfg: Dict[str, Any],
    ) -> Tuple[str, bool, int, str]:
        if not pipeline_cfg["clean_enabled"]:
            return raw_text, False, 0, "none"

        # Verbatim profile: skip all LLM passes (matches journal/dictation
        # handling via _build_cleanup_prompt → None). Without this, assistant
        # mode burned two sequential Ollama calls (~7s total) even when the
        # user explicitly asked for no processing.
        if pipeline_cfg["model_profile"] == "verbatim":
            return raw_text, False, 0, "verbatim"

        strict_prompt = self._strict_cleanup_prompt(raw_text)
        strict_text, strict_fallback, strict_ms, strict_route = (
            self._clean_blocking_with_fallback(
                strict_prompt,
                utterance_id,
                max(pipeline_cfg["active_local_timeout_ms"], 1400),
                mode="assistant",
                pipeline_cfg=pipeline_cfg,
            )
        )
        base_text = strict_text or raw_text

        compose_prompt = self._assistant_prompt(base_text, profile)
        composed_text, composed_fallback, compose_ms, compose_route = (
            self._clean_blocking_with_fallback(
                compose_prompt,
                utterance_id,
                max(pipeline_cfg["active_local_timeout_ms"] * 2, 2500),
                mode="assistant",
                pipeline_cfg=pipeline_cfg,
            )
        )
        final_text = composed_text or base_text
        route = compose_route if compose_route != "local" else strict_route
        return (
            final_text,
            (strict_fallback or composed_fallback),
            strict_ms + compose_ms,
            route,
        )

    def _paste_transcript(self, target_hwnd: Any, paste_timeout_ms: int) -> bool:
        return paste_transcript(
            target_hwnd=target_hwnd,
            paste_timeout_ms=paste_timeout_ms,
            set_foreground_window=USER32.SetForegroundWindow,
            get_foreground_window=USER32.GetForegroundWindow,
            increment_error=self._increment_error,
            status=lambda state, message: self._status(state, message),
        )

    def _append_to_journal(self, text: str, journal_file_path: str) -> Path:
        return append_to_journal(text, journal_file_path)

    def _append_to_transcript_file(
        self,
        text: str,
        transcript_file_path: str,
        tag: str = "voice-inbox",
        note_type: str = "log",
    ) -> Path:
        return append_to_transcript_file(
            text=text,
            transcript_file_path=transcript_file_path,
            tag=tag,
            note_type=note_type,
        )

    def _deliver_text(
        self,
        text: str,
        mode: str,
        utterance_id: int,
        target_hwnd: Any,
        pipeline_cfg: Dict[str, Any],
    ) -> str:
        is_latest = self._is_latest_utterance(utterance_id)
        try:
            self._copy_to_clipboard(text)
        except Exception as exc:
            self._status("ERROR", f"Clipboard copy failed: {exc}", utterance_id)
            return "copy_failed"

        if mode == "journal":
            path = self._append_to_journal(text, pipeline_cfg["journal_file_path"])
            self._status("JOURNAL", f"Saved journal entry: {path}", utterance_id)
            if pipeline_cfg["journal_paste"] and is_latest:
                pasted = self._paste_transcript(
                    target_hwnd, pipeline_cfg["paste_timeout_ms"]
                )
                return "pasted" if pasted else "clipboard_only"
            return "journal_saved"

        if mode == "meeting":
            meeting_path = self._append_to_transcript_file(
                text, pipeline_cfg["meeting_file_path"], tag="voice-meeting"
            )
            self._status(
                "MEETING", f"Saved meeting entry: {meeting_path}", utterance_id
            )
            if pipeline_cfg["meeting_paste"] and is_latest:
                pasted = self._paste_transcript(
                    target_hwnd, pipeline_cfg["paste_timeout_ms"]
                )
                return "pasted" if pasted else "clipboard_only"
            return "meeting_saved"

        inbox_path = self._append_to_transcript_file(
            text, pipeline_cfg["inbox_file_path"]
        )
        self._status("INBOX", f"Saved inbox entry: {inbox_path}", utterance_id)

        if not is_latest:
            self._status("PASTE", "Stale utterance, skipped auto-paste.", utterance_id)
            return "clipboard_only_stale"

        pasted = self._paste_transcript(target_hwnd, pipeline_cfg["paste_timeout_ms"])
        if pasted:
            self._status("PASTE", "Copied + pasted.", utterance_id)
            return "pasted"
        return "clipboard_only"

    def _build_initial_prompt(self, max_terms: int = 25) -> str:
        # Core default keywords — keeps prompt concise and well under Whisper's 224-token budget
        # to prevent prompt-echoing and token hallucinations.
        core_terms = [
            "VoicePaste",
            "Whisper",
            "Faster-Whisper",
            "Ollama",
            "Qwen",
            "Llama",
            "FastAPI",
            "Docker",
            "Tailscale",
            "Python",
            "Markdown",
            "GitHub",
        ]
        terms = list(core_terms)
        with self._phrase_lock:
            for _, right in self._phrase_exact:
                clean_right = (right or "").strip()
                if (
                    clean_right
                    and clean_right not in terms
                    and len(clean_right.split()) <= 2
                    and len(clean_right) <= 20
                ):
                    terms.append(clean_right)
                    if len(terms) >= max_terms:
                        break
        return ", ".join(terms)

    def _transcribe(
        self, wav_bytes: bytes, utterance_id: int, pipeline_cfg: Dict[str, Any]
    ) -> Tuple[Optional[str], int]:
        self._status("TRANSCRIBING", "Sending audio to STT service...", utterance_id)
        prompt = self._build_initial_prompt()
        raw_text, stt_ms, error = transcribe_audio(
            stt_url=pipeline_cfg["stt_url"],
            stt_timeout_ms=pipeline_cfg["stt_timeout_ms"],
            language=self.language,
            wav_bytes=wav_bytes,
            initial_prompt=prompt,
        )
        if error:
            self._increment_error("stt_errors")
            self._status("ERROR", error, utterance_id)
            return None, stt_ms
        return raw_text, stt_ms

    def _load_phrase_corrections(self) -> None:
        with self._config_lock:
            path = self.config.phrase_corrections_path_expanded()

        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            seed = {
                "exact": {
                    "alarma": "Ollama",
                    "olarma": "Ollama",
                    "docker compose": "docker-compose",
                },
                "regex": [
                    {"pattern": r"\bto to\b", "replace": "to"},
                ],
            }
            with path.open("w", encoding="utf-8") as handle:
                json.dump(seed, handle, indent=2)

        try:
            self._phrase_mtime = path.stat().st_mtime
        except OSError:
            pass

        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            self._status("ERROR", f"Could not load phrase corrections: {exc}")
            return

        if not isinstance(payload, dict):
            self._status("ERROR", "phrase_corrections.json root must be an object.")
            return

        phrase_exact: List[Tuple[str, str]] = []
        phrase_regex: List[Tuple[re.Pattern[str], str]] = []

        exact = payload.get("exact", {})
        if isinstance(exact, dict):
            for key, value in exact.items():
                k = str(key).strip()
                v = str(value).strip()
                if k and v:
                    phrase_exact.append((k, v))

        regex_items = payload.get("regex", [])
        if isinstance(regex_items, list):
            for item in regex_items:
                if not isinstance(item, dict):
                    continue
                pattern = str(item.get("pattern", "")).strip()
                replace = str(item.get("replace", "")).strip()
                flags = 0
                if _safe_bool(item.get("ignore_case", True), True):
                    flags |= re.IGNORECASE
                if pattern and replace:
                    try:
                        compiled = re.compile(pattern, flags)
                        phrase_regex.append((compiled, replace))
                    except re.error as exc:
                        self._status(
                            "ERROR",
                            f"Bad regex in phrase corrections ({pattern}): {exc}",
                        )

        with self._phrase_lock:
            self._phrase_exact = phrase_exact
            self._phrase_regex = phrase_regex

    def _ensure_phrase_corrections_fresh(self) -> None:
        try:
            path = self.config.phrase_corrections_path_expanded()
            if path.exists():
                mtime = path.stat().st_mtime
                if mtime != self._phrase_mtime:
                    self._load_phrase_corrections()
        except OSError:
            pass

    def _apply_phrase_corrections(self, text: str) -> Tuple[str, List[str]]:
        self._ensure_phrase_corrections_fresh()
        with self._phrase_lock:
            phrase_exact = list(self._phrase_exact)
            phrase_regex = list(self._phrase_regex)
        return apply_phrase_corrections(text, phrase_exact, phrase_regex)

    def _add_phrase_correction_pair(self, wrong: str, right: str) -> None:
        path = self.config.phrase_corrections_path_expanded()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: Dict[str, Any] = {"exact": {}, "regex": []}
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                    if isinstance(loaded, dict):
                        data = loaded
            except Exception:
                pass
        exact = data.setdefault("exact", {})
        exact[wrong.strip().lower()] = right.strip()
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        self._load_phrase_corrections()

        # Asynchronously push to NucBox STT service
        with self._config_lock:
            stt_url = self.config.stt_url
        threading.Thread(
            target=push_vocabulary_correction,
            args=(stt_url, wrong, right),
            daemon=True,
        ).start()

    def _sync_remote_vocabulary(self) -> None:
        """Fetch remote vocabulary from NucBox on boot and merge into local cache."""
        try:
            with self._config_lock:
                stt_url = self.config.stt_url
            remote_data = fetch_remote_vocabulary(stt_url, timeout_seconds=2.0)
            if not remote_data or not isinstance(remote_data, dict):
                return
            remote_corrections = remote_data.get("phrase_corrections", {})
            if not isinstance(remote_corrections, dict) or not remote_corrections:
                return

            path = self.config.phrase_corrections_path_expanded()
            payload: Dict[str, Any] = {"exact": {}, "regex": []}
            if path.exists():
                try:
                    with path.open("r", encoding="utf-8") as handle:
                        loaded = json.load(handle)
                        if isinstance(loaded, dict):
                            payload = loaded
                except Exception:
                    pass

            exact = payload.setdefault("exact", {})
            updated = False
            for k, v in remote_corrections.items():
                k_clean = str(k).strip().lower()
                v_clean = str(v).strip()
                if k_clean and v_clean and exact.get(k_clean) != v_clean:
                    exact[k_clean] = v_clean
                    updated = True

            if updated:
                with path.open("w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, ensure_ascii=False)
                    handle.write("\n")
                self._load_phrase_corrections()
        except Exception as exc:
            logging.debug("Remote vocabulary sync skipped: %s", exc)


    def _load_snippets(self) -> None:
        with self._config_lock:
            path = self.config.snippets_path_expanded()
        snippets = load_snippets(path)
        with self._snippets_lock:
            self._snippet_pairs = snippets

    def _apply_snippets(self, text: str) -> Tuple[str, List[str]]:
        with self._snippets_lock:
            snippets = list(self._snippet_pairs)
        return apply_snippets(text, snippets)

    def _dedupe_consecutive_sentences(self, text: str) -> str:
        return dedupe_consecutive_sentences(text)

    def _dedupe_repeated_ngrams(self, text: str) -> str:
        return dedupe_repeated_ngrams(text)

    def _post_clean_dedupe(self, text: str) -> str:
        return post_clean_dedupe(text)

    def _light_post_polish(self, text: str) -> str:
        return light_post_polish(text)

    def _process_utterance(
        self,
        utterance_id: int,
        wav_bytes: bytes,
        target_hwnd: Any,
        capture_ms: int,
        mode: str,
        assistant_profile: str,
        pipeline_cfg: Dict[str, Any],
        meeting_session_id: Optional[str] = None,
        partial_text: str = "",
    ) -> None:
        event: Dict[str, Any] = {
            "utterance_id": utterance_id,
            "mode": mode,
            "assistant_profile": assistant_profile,
            "model_profile": pipeline_cfg["model_profile"],
            "active_model": pipeline_cfg["active_local_model"],
            "warm_state": self._warm_state,
            "stt_text_raw": "",
            "stt_text_corrected": "",
            "text_cleaned": "",
            "paste_result": "none",
            "fallback_used": False,
            "corrections_applied": [],
            "voice_commands_applied": [],
            "route_used": "none",
            "partial_text": partial_text,
            "finalization_source": "partial+final" if partial_text else "final_only",
            "meeting_session_id": meeting_session_id or "",
            "timings_ms": {},
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }

        total_start = time.perf_counter()
        if not self._check_stt_health(force=False):
            self._status(
                "STATUS",
                "STT preflight failed; attempting request anyway (degraded mode).",
                utterance_id,
            )

        raw_text, stt_ms = self._transcribe(wav_bytes, utterance_id, pipeline_cfg)
        if (raw_text is None) and mode == "meeting" and meeting_session_id:
            self._status(
                "MEETING", "Chunk transcription failed, retrying once...", utterance_id
            )
            retry_text, retry_ms = self._transcribe(
                wav_bytes, utterance_id, pipeline_cfg
            )
            stt_ms += retry_ms
            raw_text = retry_text
        event["timings_ms"]["capture"] = capture_ms
        event["timings_ms"]["stt"] = stt_ms
        if raw_text is None:
            if mode == "meeting" and meeting_session_id:
                placeholder = f"[Chunk failed: {datetime.now().strftime('%H:%M:%S')}]"
                self._append_to_transcript_file(
                    placeholder, pipeline_cfg["meeting_file_path"]
                )
                event["paste_result"] = "meeting_chunk_failed_saved"
            else:
                event["paste_result"] = "stt_failed"
            event["timings_ms"]["total"] = int(
                (time.perf_counter() - total_start) * 1000
            )
            self._record_stats(event)
            self._event(event)
            return

        if not raw_text:
            self._status("ERROR", "No speech detected.", utterance_id)
            event["paste_result"] = "empty"
            event["timings_ms"]["total"] = int(
                (time.perf_counter() - total_start) * 1000
            )
            self._record_stats(event)
            self._event(event)
            return

        corrected_text, corrections = self._apply_phrase_corrections(raw_text)
        deduped_input = self._post_clean_dedupe(corrected_text)
        if deduped_input != corrected_text:
            corrections.append("post_dedupe:input")
            corrected_text = deduped_input

        voice_commands_applied: List[str] = []
        if pipeline_cfg["voice_commands_enabled"] and mode in {
            "dictation",
            "journal",
            "meeting",
        }:
            corrected_text, voice_commands_applied = apply_voice_commands(
                corrected_text
            )
            for cmd in voice_commands_applied:
                if cmd.startswith("add_correction:"):
                    parts = cmd[len("add_correction:") :].split("->", 1)
                    if len(parts) == 2:
                        self._add_phrase_correction_pair(parts[0], parts[1])

        if corrections:
            self._status(
                "CLEANING",
                f"Applied {len(corrections)} phrase correction(s).",
                utterance_id,
            )
        if voice_commands_applied:
            self._status(
                "CLEANING",
                f"Applied {len(voice_commands_applied)} voice command(s).",
                utterance_id,
            )

        event["stt_text_raw"] = raw_text
        event["stt_text_corrected"] = corrected_text
        event["corrections_applied"] = corrections
        event["voice_commands_applied"] = voice_commands_applied
        cleaned_text = corrected_text
        fallback_used = False
        cleanup_ms = 0
        route_used = "local"

        if mode == "assistant":
            self._status(
                "CLEANING", f"Assistant mode ({assistant_profile})...", utterance_id
            )
            cleaned_text, fallback_used, cleanup_ms, route_used = (
                self._clean_for_assistant(
                    corrected_text,
                    utterance_id,
                    assistant_profile,
                    pipeline_cfg,
                )
            )
        elif mode == "journal":
            self._status("CLEANING", "Journal cleanup...", utterance_id)
            cleaned_text, fallback_used, cleanup_ms, route_used = (
                self._clean_for_journal(corrected_text, utterance_id, pipeline_cfg)
            )
        elif mode == "meeting":
            self._status("CLEANING", "Meeting cleanup...", utterance_id)
            cleaned_text, fallback_used, cleanup_ms, route_used = (
                self._clean_for_journal(corrected_text, utterance_id, pipeline_cfg)
            )
        else:
            self._status("CLEANING", "Dictation cleanup...", utterance_id)
            cleaned_text, fallback_used, cleanup_ms, route_used = (
                self._clean_dictation_latency_first(
                    corrected_text,
                    utterance_id,
                    pipeline_cfg,
                    target_hwnd,
                )
            )

        # Reset consecutive-fallback streak on any successful cleanup route.
        # "none" is the only route emitted on raw fallback; verbatim/local/cloud all indicate
        # the cleanup layer ran (or was intentionally skipped), so the streak is not degradation.
        if route_used != "none":
            with self._lock:
                self._consecutive_fallbacks = 0

        if pipeline_cfg["model_profile"] != "verbatim":
            deduped_output = self._post_clean_dedupe(cleaned_text)
            if deduped_output != cleaned_text:
                self._status("CLEANING", "Collapsed repeated words/phrases.", utterance_id)
                cleaned_text = deduped_output

            if mode in {"dictation", "journal", "meeting"}:
                if pipeline_cfg["smart_formatting_enabled"]:
                    polished_text = self._light_post_polish(cleaned_text)
                    if polished_text and polished_text != cleaned_text:
                        self._status(
                            "CLEANING", "Applied light punctuation polish.", utterance_id
                        )
                        cleaned_text = polished_text

        cleaned_text, snippets_applied = self._apply_snippets(cleaned_text)
        if snippets_applied:
            self._status(
                "CLEANING", f"Applied {len(snippets_applied)} snippet(s).", utterance_id
            )

        event["text_cleaned"] = cleaned_text
        event["fallback_used"] = fallback_used
        event["route_used"] = route_used
        event["timings_ms"]["cleanup"] = cleanup_ms
        event["paste_result"] = self._deliver_text(
            cleaned_text, mode, utterance_id, target_hwnd, pipeline_cfg
        )
        event["timings_ms"]["total"] = int((time.perf_counter() - total_start) * 1000)
        self._record_stats(event)
        self._status(
            "DONE",
            f"Mode={mode} chars={len(cleaned_text)} total={event['timings_ms']['total']}ms",
            utterance_id,
        )
        self._event(event)

    def _warmup(self) -> None:
        with self._config_lock:
            clean_enabled = self.config.clean_enabled
            warmup_enabled = self.config.warmup_enabled
            model_profile = self.config.model_profile
            active_local_model = self.config.active_local_model
            model_request_timeout_ms = self.config.model_request_timeout_ms
            active_local_timeout_ms = self.config.active_local_timeout_ms
            pipeline_cfg = self._pipeline_config_snapshot()

        if (not clean_enabled) or (not warmup_enabled) or (model_profile == "verbatim"):
            return
        self._warm_state = "warming"
        self._status("WARMUP", f"Warming model {active_local_model}...")
        try:
            warmup_timeout = max(model_request_timeout_ms, active_local_timeout_ms * 3)
            self._call_ollama_generate(
                active_local_model,
                "Reply with: ready",
                warmup_timeout,
                num_predict=8,
                pipeline_cfg=pipeline_cfg,
            )
            self._warm_state = "warm"
            self._status("WARMUP", "Model warmup completed.")
            self._beep("ok")
        except Exception as exc:
            self._warm_state = "error"
            self._status("WARMUP", f"Warmup skipped: {exc}")

    def warm_selected_model_now(self, background: bool = True) -> None:
        if background:
            threading.Thread(target=self._warmup, daemon=True).start()
        else:
            self._warmup()

    def _vram_poll_worker(self) -> None:
        """Background thread: poll Ollama /api/ps every 30 s to track VRAM state."""
        POLL_INTERVAL_S = 30
        while not self._vram_poll_stop_event.wait(timeout=POLL_INTERVAL_S):
            self.ensure_keyboard_hooks()
            with self._config_lock:
                ollama_url = self.config.ollama_url
                active_model = self.config.active_local_model
                model_profile = self.config.model_profile

            if self._warm_state == "warming" or model_profile == "verbatim":
                continue

            result = check_model_loaded_in_vram(ollama_url, active_model)
            if result is True and self._warm_state in ("cold", "error"):
                self._warm_state = "warm"
                self._status("WARMUP", f"Model {active_model} detected in VRAM.")
            elif result is False and self._warm_state == "warm":
                self._warm_state = "cold"
                self._status(
                    "WARMUP",
                    f"Model {active_model} no longer in VRAM (evicted or Ollama restarted).",
                )

    def startup(self) -> None:
        self._status("START", "VoicePaste starting.")
        with self._config_lock:
            display_cfg = self.config.display()
            mode_default = self.config.mode_default
            log_dir = self.config.log_dir
            log_retention_days = self.config.log_retention_days
            transcript_dirs = self.config.ensure_voice_paste_directories()
        for key, value in display_cfg.items():
            self._status("CONFIG", f"{key}={value}")
        self._status(
            "CONFIG",
            "Voice paste folders: "
            f"inbox={transcript_dirs['inbox']} | "
            f"journal={transcript_dirs['journal']} | "
            f"meetings={transcript_dirs['meetings']}",
        )
        prune_result = prune_old_logs(_expand_path(log_dir), log_retention_days)
        self._status(
            "LOGS",
            f"Log retention: scanned={prune_result['scanned']} deleted={prune_result['deleted']} keep_days={prune_result['retention_days']}",
        )
        self._set_mode(mode_default, announce=False)
        self._check_stt_health(force=True)
        if not self._stt_available:
            self._status("STATUS", "STT unavailable at startup (degraded mode).")
            self._beep("warning")
        self._warmup()
        # Start VRAM polling thread to keep warm state accurate
        self._vram_poll_stop_event.clear()
        self._vram_poll_thread = threading.Thread(
            target=self._vram_poll_worker, daemon=True, name="vram-poll"
        )
        self._vram_poll_thread.start()

    def shutdown(self) -> None:
        self._partial_stop_event.set()
        self._vram_poll_stop_event.set()
        if self._vram_poll_thread is not None:
            self._vram_poll_thread.join(timeout=2.0)
            self._vram_poll_thread = None
        if self._partial_thread is not None:
            self._partial_thread.join(timeout=1.0)
            self._partial_thread = None
        if self.is_meeting_session_active():
            self.stop_meeting_session(announce=False)
        with self._lock:
            stream = self._stream
            self._recording = False
            self._stream = None
            self._frames = []
            self._target_hwnd = None
            self._partial_stabilizers.clear()
            self._partial_text_by_utterance.clear()
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self.uninstall_keyboard_hooks()
        self._executor.shutdown(wait=False, cancel_futures=False)
        self._status("STOP", f"Error counters: {self._error_counts}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--config", default=None, help="Path to JSON config file")
    parser.add_argument("--stt-url", default=None)
    parser.add_argument("--ollama-url", default=None)
    parser.add_argument("--clean-model-local", default=None)
    parser.add_argument("--clean-model-fallback", default=None)
    parser.add_argument("--local-clean-timeout-ms", default=None, type=int)
    parser.add_argument("--cloud-clean-timeout-ms", default=None, type=int)
    parser.add_argument("--model-request-timeout-ms", default=None, type=int)
    parser.add_argument("--stt-timeout-ms", default=None, type=int)
    parser.add_argument("--paste-timeout-ms", default=None, type=int)
    parser.add_argument("--mode", choices=sorted(VALID_MODES), default=None)
    parser.add_argument("--voice-paste-root", default=None)
    parser.add_argument("--journal-path", default=None)
    parser.add_argument("--journal-paste", action="store_true", default=None)
    parser.add_argument("--meeting-paste", action="store_true", default=None)
    parser.add_argument(
        "--no-meeting-paste", dest="meeting_paste", action="store_false"
    )
    parser.add_argument("--log-dir", default=None)
    parser.add_argument("--log-retention-days", type=int, default=None)
    parser.add_argument("--cloud-breaker-threshold", type=int, default=None)
    parser.add_argument("--cloud-breaker-cooldown-s", type=int, default=None)
    parser.add_argument("--stt-health-check-interval-s", type=int, default=None)
    parser.add_argument("--warmup-enabled", action="store_true", default=None)
    parser.add_argument("--ollama-keep-alive", default=None)
    parser.add_argument("--clean", dest="clean", action="store_true", default=None)
    parser.add_argument("--no-clean", dest="clean", action="store_false")
    parser.add_argument("--app-mode", choices=sorted(VALID_APP_MODES), default=None)
    parser.add_argument(
        "--model-profile", choices=sorted(VALID_MODEL_PROFILES), default=None
    )
    parser.add_argument("--fast-model", default=None)
    parser.add_argument("--quality-model", default=None)
    parser.add_argument("--fast-local-timeout-ms", type=int, default=None)
    parser.add_argument("--quality-local-timeout-ms", type=int, default=None)
    parser.add_argument("--cloud-fallback-enabled", action="store_true", default=None)
    parser.add_argument("--claude-enabled", action="store_true", default=None)
    parser.add_argument("--claude-model", default=None)
    parser.add_argument("--phrase-corrections-path", default=None)
    parser.add_argument(
        "--partial-transcript-enabled", action="store_true", default=None
    )
    parser.add_argument("--partial-update-interval-ms", type=int, default=None)
    parser.add_argument("--smart-formatting-enabled", action="store_true", default=None)
    parser.add_argument("--voice-commands-enabled", action="store_true", default=None)
    parser.add_argument("--meeting-session-chunk-seconds", type=int, default=None)
    parser.add_argument("--snippets-path", default=None)
    parser.add_argument("--hud-enabled", action="store_true", default=None)
    parser.add_argument(
        "--no-hud-enabled", dest="hud_enabled", action="store_false"
    )
    parser.add_argument("--hide-on-close", action="store_true", default=None)
    parser.add_argument("--audio-feedback", action="store_true", default=None)
    parser.add_argument(
        "--no-audio-feedback", dest="audio_feedback", action="store_false"
    )
    return parser


def run_cli(args: argparse.Namespace) -> None:
    if getattr(args, "version", False):
        print(f"VoicePaste {__version__}")
        return

    try:
        config = VoicePasteConfig.load(args)
    except Exception as exc:
        print(f"Failed to load configuration: {exc}")
        raise SystemExit(1)

    config.app_mode = "cli"
    client = PushToTalkClient(config)
    client.startup()
    client.install_keyboard_hooks()
    quit_hotkey = (config.quit_hotkey or DEFAULT_QUIT_HOTKEY).strip().lower()
    quit_requested = threading.Event()
    def _request_quit() -> None:
        print(f"Quit hotkey pressed ({quit_hotkey}). Shutting down...")
        quit_requested.set()

    quit_ref = keyboard.add_hotkey(quit_hotkey, _request_quit)

    print(
        "Hold Left Ctrl + Left Alt to record (fallback: Ctrl + Numpad 0). "
        "Release either key to transcribe."
    )
    print(f"Quit hotkey: {quit_hotkey}")
    print(
        "Mode hotkeys: "
        f"{MODE_HOTKEYS['dictation']}=dictation, "
        f"{MODE_HOTKEYS['assistant']}=assistant, "
        f"{MODE_HOTKEYS['journal']}=journal, "
        f"{MODE_HOTKEYS['meeting']}=meeting"
    )
    print(
        "Assistant profile hotkeys: "
        f"{PROFILE_HOTKEYS['email']}=email, "
        f"{PROFILE_HOTKEYS['chat']}=chat, "
        f"{PROFILE_HOTKEYS['neutral']}=neutral"
    )
    print(
        "Model profile hotkeys: "
        f"{MODEL_HOTKEYS['fast']}=fast, "
        f"{MODEL_HOTKEYS['quality']}=quality"
    )
    print("Press Ctrl+C to exit.")

    try:
        while not quit_requested.wait(timeout=0.2):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        try:
            keyboard.remove_hotkey(quit_ref)
        except Exception:
            pass
        client.shutdown()


def main_cli() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run_cli(args)


if __name__ == "__main__":
    main_cli()
