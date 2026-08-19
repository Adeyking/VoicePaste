import json
from pathlib import Path

from voicepaste.snippets import apply_snippets, load_snippets


def test_load_snippets_creates_file_when_missing(tmp_path: Path) -> None:
    snippets_path = tmp_path / "snippets.json"
    pairs = load_snippets(snippets_path)
    assert pairs == []
    assert snippets_path.exists()


def test_apply_snippets_exact_word_boundary() -> None:
    text, applied = apply_snippets("brb please. brb-now should not expand", [("brb", "be right back")])
    assert text.startswith("be right back please.")
    assert "brb-now should not expand" in text
    assert applied == ["brb->be right backx1"]


def test_load_snippets_reads_exact_pairs(tmp_path: Path) -> None:
    snippets_path = tmp_path / "snippets.json"
    snippets_path.write_text(json.dumps({"exact": {"ty": "thank you"}}), encoding="utf-8")
    pairs = load_snippets(snippets_path)
    assert pairs == [("ty", "thank you")]
