import json
from pathlib import Path

from voicepaste.engine import PushToTalkClient, VoicePasteConfig, build_parser


def _build_config(tmp_path: Path) -> VoicePasteConfig:
    cfg_path = tmp_path / "voicepaste.config.json"
    payload = {
        "STT_URL": "http://127.0.0.1:8770/transcribe",
        "OLLAMA_URL": "http://127.0.0.1:11434",
        "LOG_DIR": str(tmp_path / "logs"),
        "MODE_DEFAULT": "dictation",
    }
    cfg_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args([])
    args.config = str(cfg_path)
    return VoicePasteConfig.load(args)


def test_set_mode_persists_config(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    client = PushToTalkClient(config)
    client.set_mode("journal", persist=True)
    saved = json.loads(config.config_path.read_text(encoding="utf-8"))
    assert saved["MODE_DEFAULT"] == "journal"
    assert client.get_mode() == "journal"


def test_invalid_mode_is_ignored(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    client = PushToTalkClient(config)
    client.set_mode("invalid-mode", persist=False)
    assert client.get_mode() == "dictation"


def test_set_model_profile_switches_without_crashing(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    client = PushToTalkClient(config)
    client.set_model_profile("quality", announce=False, warm=False, persist=False)
    assert client.get_model_profile() == "quality"
    assert client.get_active_local_model() == config.quality_model


def test_meeting_mode_delivery_does_not_crash(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    client = PushToTalkClient(config)
    pipeline_cfg = client._pipeline_config_snapshot()
    pipeline_cfg["meeting_file_path"] = str(tmp_path / "meetings" / "2026-08-06.md")
    result = client._deliver_text(
        text="Testing meeting delivery",
        mode="meeting",
        utterance_id=1,
        target_hwnd=None,
        pipeline_cfg=pipeline_cfg,
    )
    assert result == "meeting_saved"
    meeting_file = Path(pipeline_cfg["meeting_file_path"])
    assert meeting_file.exists()
    assert "Testing meeting delivery" in meeting_file.read_text(encoding="utf-8")

