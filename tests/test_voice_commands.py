from voicepaste.voice_commands import apply_voice_commands


def test_voice_commands_formatting_tokens() -> None:
    text, applied = apply_voice_commands("hello new line world comma nice period")
    assert text == "hello\nworld, nice."
    assert any(a.startswith("new_line") for a in applied)
    assert any(a.startswith("comma") for a in applied)


def test_voice_commands_literal_escape() -> None:
    text, applied = apply_voice_commands("print literal new line exactly")
    assert "new line" in text
    assert "literal:new line" in applied


def test_voice_commands_backtrack_scratch_that() -> None:
    text, applied = apply_voice_commands("first sentence. wrong clause scratch that final sentence")
    assert text == "first sentence. final sentence"
    assert "scratch_that" in applied


def test_obsidian_tag_task_formatting() -> None:
    text, applied = apply_voice_commands("tag task buy milk and eggs")
    assert text == "- [ ] buy milk and eggs"
    assert any("obsidian:tag_task" in a for a in applied)


def test_obsidian_tag_idea_formatting() -> None:
    text, applied = apply_voice_commands("tag idea automated workflow")
    assert text == "- 💡 **Idea**: automated workflow"
    assert any("obsidian:tag_idea" in a for a in applied)


def test_obsidian_note_callout_formatting() -> None:
    text, applied = apply_voice_commands("insert note callout This is an important update")
    assert text == "> [!NOTE]\nThis is an important update"
    assert "obsidian:note_callout" in applied


def test_voice_commands_preserves_numbers_versions_and_ips() -> None:
    text, _ = apply_voice_commands("upgrade to version 2.0 and 3.0 on 192.168.1.100:8770 with qwen2.5:3b")
    assert text == "upgrade to version 2.0 and 3.0 on 192.168.1.100:8770 with qwen2.5:3b"
