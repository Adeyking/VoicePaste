from datetime import datetime
from pathlib import Path
from voicepaste.delivery import append_to_journal, append_to_transcript_file


def test_append_to_transcript_file_creates_frontmatter_on_new_file(tmp_path: Path) -> None:
    target_file = tmp_path / "inbox" / "2026-07-30.md"
    assert not target_file.exists()

    append_to_transcript_file("Hello world text", str(target_file))

    assert target_file.exists()
    content = target_file.read_text(encoding="utf-8")

    today = datetime.now().strftime("%Y-%m-%d")
    expected_frontmatter = (
        "---\n"
        "type: log\n"
        "status: active\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        "tags: [voice-inbox]\n"
        "---\n"
    )
    assert content.startswith(expected_frontmatter)
    assert "Hello world text" in content


def test_append_to_transcript_file_skips_frontmatter_on_existing_file(tmp_path: Path) -> None:
    target_file = tmp_path / "inbox" / "2026-07-30.md"
    append_to_transcript_file("First entry", str(target_file))

    first_content = target_file.read_text(encoding="utf-8")
    assert first_content.count("---") == 2  # Exactly one frontmatter block

    append_to_transcript_file("Second entry", str(target_file))

    second_content = target_file.read_text(encoding="utf-8")
    assert second_content.count("---") == 2  # Frontmatter not duplicated
    assert "First entry" in second_content
    assert "Second entry" in second_content


def test_append_to_journal_uses_journal_tag(tmp_path: Path) -> None:
    target_file = tmp_path / "journal" / "2026-07-30.md"
    append_to_journal("Journal thoughts", str(target_file))

    content = target_file.read_text(encoding="utf-8")
    assert "tags: [voice-journal]" in content
    assert "Journal thoughts" in content
