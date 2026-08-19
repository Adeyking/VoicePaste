import json
from pathlib import Path

from voicepaste import defaults
from voicepaste.engine import VoicePasteConfig, build_parser


def _load_config(tmp_path: Path, payload: dict) -> VoicePasteConfig:
    cfg_path = tmp_path / "voicepaste.config.json"
    cfg_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args([])
    args.config = str(cfg_path)
    return VoicePasteConfig.load(args)


def test_transcript_file_paths_follow_mode_folders(tmp_path: Path) -> None:
    from datetime import datetime
    root = tmp_path / "voice_paste"
    config = _load_config(
        tmp_path,
        {
            "STT_URL": "http://127.0.0.1:8770/transcribe",
            "OLLAMA_URL": "http://127.0.0.1:11434",
            "VOICE_PASTE_ROOT": str(root),
            "MODE_DEFAULT": "dictation",
        },
    )
    now = datetime.now()
    year_str = now.strftime("%Y")
    month_str = now.strftime("%m")
    assert config.transcript_file_path_for_mode("dictation").parent == root / "inbox" / year_str / month_str
    assert config.transcript_file_path_for_mode("assistant").parent == root / "inbox" / year_str / month_str
    assert config.transcript_file_path_for_mode("journal").parent == root / "journal" / year_str / month_str
    assert config.transcript_file_path_for_mode("meeting").parent == root / "meetings" / year_str / month_str


def test_voice_paste_root_derives_from_legacy_journal_path(tmp_path: Path) -> None:
    journal_dir = tmp_path / "Journal"
    config = _load_config(
        tmp_path,
        {
            "STT_URL": "http://127.0.0.1:8770/transcribe",
            "OLLAMA_URL": "http://127.0.0.1:11434",
            "JOURNAL_PATH": str(journal_dir),
            "MODE_DEFAULT": "meeting",
        },
    )
    assert config.mode_default == "meeting"
    assert config.voice_paste_root_path() == tmp_path


def test_default_paths_follow_voicepaste_layout(tmp_path: Path) -> None:
    config = _load_config(
        tmp_path,
        {
            "STT_URL": "http://127.0.0.1:8770/transcribe",
            "OLLAMA_URL": "http://127.0.0.1:11434",
        },
    )
    assert "VoicePaste" in defaults.DEFAULT_VOICE_PASTE_ROOT
    assert "VoicePaste" in defaults.DEFAULT_JOURNAL_PATH
    assert "VoicePaste" in defaults.DEFAULT_LOG_DIR
    assert "VoicePaste" in defaults.DEFAULT_SNIPPETS_PATH
    assert "VoicePaste" in str(config.voice_paste_root_path())
