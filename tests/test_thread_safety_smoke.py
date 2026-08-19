import json
import threading
from pathlib import Path
from typing import Any, Dict, List

from voicepaste.engine import PushToTalkClient, VoicePasteConfig, build_parser


def _build_config(tmp_path: Path) -> VoicePasteConfig:
    cfg_path = tmp_path / "voicepaste.config.json"
    corrections_path = tmp_path / "phrase_corrections.json"
    corrections_path.write_text('{"exact":{"alarma":"Ollama"},"regex":[]}', encoding="utf-8")

    payload: Dict[str, Any] = {
        "STT_URL": "http://127.0.0.1:8770/transcribe",
        "OLLAMA_URL": "http://127.0.0.1:11434",
        "LOG_DIR": str(tmp_path / "logs"),
        "PHRASE_CORRECTIONS_PATH": str(corrections_path),
        "LOG_RETENTION_DAYS": 30,
    }
    cfg_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args([])
    args.config = str(cfg_path)
    return VoicePasteConfig.load(args)


def test_runtime_config_and_fallback_counters_are_thread_safe(tmp_path: Path) -> None:
    client = PushToTalkClient(_build_config(tmp_path))
    errors: List[Exception] = []

    def updater() -> None:
        for i in range(120):
            try:
                client.update_runtime_config(
                    {
                        "MODEL_PROFILE": "fast" if i % 2 == 0 else "quality",
                        "MODE_DEFAULT": "dictation" if i % 3 else "assistant",
                    },
                    persist=False,
                )
            except Exception as exc:  # pragma: no cover - should remain empty
                errors.append(exc)

    def fallback_churn() -> None:
        for _ in range(400):
            try:
                snapshot = client._pipeline_config_snapshot()
                client._cloud_failure(snapshot)
                client._cloud_success()
            except Exception as exc:  # pragma: no cover - should remain empty
                errors.append(exc)

    def reader() -> None:
        for _ in range(400):
            try:
                snapshot = client._pipeline_config_snapshot()
                client._cloud_fallback_allowed("assistant", snapshot)
                client._apply_phrase_corrections("alarma test")
            except Exception as exc:  # pragma: no cover - should remain empty
                errors.append(exc)

    threads = [
        threading.Thread(target=updater),
        threading.Thread(target=fallback_churn),
        threading.Thread(target=reader),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert client.get_model_profile() in {"fast", "quality"}
    stats = client.get_stats()
    assert "uptime_s" in stats
    assert "avg_total_ms" in stats
    assert "error_counts" in stats
    with client._fallback_lock:
        assert client._cloud_failure_count >= 0
        assert client._cloud_breaker_open_until >= 0.0
