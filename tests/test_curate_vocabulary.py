import json
from pathlib import Path
from voicepaste.curate_vocabulary import curate_vocabulary_from_logs_and_inbox


def test_curate_vocabulary_extracts_corrections_from_logs(tmp_path: Path) -> None:
    log_dir = tmp_path / "Logs"
    log_dir.mkdir()
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    corrections_file = tmp_path / "phrase_corrections.json"

    # Create a dummy log file with an STT event diff
    log_file = log_dir / "voicepaste-2026-08-07.log"
    log_content = (
        '2026-08-07 12:00:00 [INFO] EVENT {"timestamp": "2026-08-07T12:00:00", '
        '"utterance_id": 1, "stt_text_raw": "nucbox ollama", "stt_text_corrected": "NucBox Ollama", "corrections_applied": []}\n'
    )
    log_file.write_text(log_content, encoding="utf-8")

    # Run curation
    res = curate_vocabulary_from_logs_and_inbox(
        log_dir=log_dir,
        inbox_dir=inbox_dir,
        phrase_corrections_path=corrections_file,
    )

    assert res["scanned_logs"] == 1
    assert res["new_pairs_added"] >= 1
    assert corrections_file.exists()

    with corrections_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["exact"]["nucbox"] == "NucBox"


def test_curate_vocabulary_extracts_tech_terms_from_inbox(tmp_path: Path) -> None:
    log_dir = tmp_path / "Logs"
    log_dir.mkdir()
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    corrections_file = tmp_path / "phrase_corrections.json"

    # Create a dummy inbox markdown note with tech proper nouns
    note_file = inbox_dir / "2026-08-07.md"
    note_file.write_text("Discussing OpenWebUI and NucBox architecture.\n", encoding="utf-8")

    res = curate_vocabulary_from_logs_and_inbox(
        log_dir=log_dir,
        inbox_dir=inbox_dir,
        phrase_corrections_path=corrections_file,
    )

    assert res["scanned_inbox_notes"] == 1
    assert res["new_pairs_added"] >= 1

    with corrections_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
        assert "openwebui" in data["exact"]
        assert data["exact"]["openwebui"] == "OpenWebUI"
