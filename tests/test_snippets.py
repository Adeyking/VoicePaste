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


def test_engine_snippets_hot_reload_and_resilience(tmp_path: Path) -> None:
    import time
    from voicepaste.engine import PushToTalkClient, VoicePasteConfig, build_parser

    snippets_path = tmp_path / "snippets.json"
    snippets_path.write_text(json.dumps({"exact": {"ty": "thank you"}}), encoding="utf-8")

    args = build_parser().parse_args([
        "--stt-url", "http://localhost:8770",
        "--ollama-url", "http://localhost:11434",
        "--snippets-path", str(snippets_path),
    ])
    cfg = VoicePasteConfig.load(args)
    client = PushToTalkClient(cfg)

    # Initial snippet applied
    out, applied = client._apply_snippets("say ty")
    assert out == "say thank you"

    # Now update snippets.json on disk with a new trigger
    time.sleep(0.01)  # Ensure mtime advances
    snippets_path.write_text(json.dumps({"exact": {"ty": "thank you", "np": "no problem"}}), encoding="utf-8")

    out2, applied2 = client._apply_snippets("say np")
    assert out2 == "say no problem"

    # Now simulate a transient read error or empty return: previous cache is preserved!
    time.sleep(0.01)
    snippets_path.write_text("invalid json {{{", encoding="utf-8")
    out3, applied3 = client._apply_snippets("say np")
    assert out3 == "say no problem"

