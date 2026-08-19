import re

import pytest

from voicepaste.text_processing import (
    apply_phrase_corrections,
    dedupe_consecutive_sentences,
    dedupe_repeated_ngrams,
    light_post_polish,
    post_clean_dedupe,
    sanitize_model_output,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("   ", ""),
        ("```text\nhello world\n```", "hello world"),
        ("**hello world**", "hello world"),
        ("Sure, here is the cleaned transcript: hello", "hello"),
        ("Output: hello", "hello"),
        ("Rewritten text: hello", "hello"),
        ("cleaned transcript:\nhello\nthere", "hello there"),
        ("Here is the output:\nline one\nline two", "line one line two"),
        ("Plain output line", "Plain output line"),
    ],
)
def test_sanitize_model_output(raw: str, expected: str) -> None:
    assert sanitize_model_output(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("This is a test. This is a test.", "This is a test."),
        (
            "I am going to the store today. I am going to the store today after lunch.",
            "I am going to the store today after lunch.",
        ),
        ("Short. Short.", "Short."),
        ("One two three. One two three?", "One two three."),
        ("First sentence. Second sentence.", "First sentence. Second sentence."),
        ("Hello world! Hello world!", "Hello world!"),
        ("alpha beta gamma. alpha beta gamma delta.", "alpha beta gamma delta."),
    ],
)
def test_dedupe_consecutive_sentences(raw: str, expected: str) -> None:
    assert dedupe_consecutive_sentences(raw) == expected


def test_dedupe_consecutive_sentences_handles_missing_space_after_punctuation() -> None:
    raw = "It's not working as well as it did before.It's not working as well as it did before."
    assert dedupe_consecutive_sentences(raw) == "It's not working as well as it did before."


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("please send please send the update", "please send the update"),
        ("to John to John by noon", "to John by noon"),
        ("a b c a b c", "a b c"),
        ("alpha alpha alpha beta", "alpha beta"),
        ("( hello ) ( hello )", "(hello) (hello)"),
        ("word, word, next", "word, next"),
        ("one two three", "one two three"),
        ("go go go go now", "go go now"),
    ],
)
def test_dedupe_repeated_ngrams(raw: str, expected: str) -> None:
    assert dedupe_repeated_ngrams(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("um i am here", "I am here."),
        ("uh, this is fine", "This is fine."),
        ("i like this", "I like this."),
        ("hello world.", "Hello world."),
        ("are you okay? yes i am", "Are you okay? Yes I am."),
        ("( hello )", "(Hello)."),
        ("", ""),
    ],
)
def test_light_post_polish(raw: str, expected: str) -> None:
    assert light_post_polish(raw) == expected


def test_post_clean_dedupe_combines_sentence_and_ngram_rules() -> None:
    raw = "Please send the email. Please send the email. to John to John."
    assert post_clean_dedupe(raw) == "Please send the email. to John"


def test_post_clean_dedupe_handles_no_space_sentence_duplication() -> None:
    raw = "It's not working as well as it did before.It's not working as well as it did before."
    assert post_clean_dedupe(raw) == "It's not working as well as it did before."


def test_apply_phrase_corrections_exact_and_regex() -> None:
    phrase_exact = [("alarma", "Ollama"), ("fast api", "FastAPI")]
    phrase_regex = [(re.compile(r"\bto to\b", re.IGNORECASE), "to")]
    text, applied = apply_phrase_corrections("alarma sent to to FastAPI", phrase_exact, phrase_regex)
    assert text == "Ollama sent to FastAPI"
    assert "exact:alarma->Ollamax1" in applied
    assert "regex:\\bto to\\b->tox1" in applied


def test_apply_phrase_corrections_case_insensitive_exact() -> None:
    phrase_exact = [("hello world", "Hello World")]
    text, applied = apply_phrase_corrections("HELLO WORLD", phrase_exact, [])
    assert text == "Hello World"
    assert applied == ["exact:hello world->Hello Worldx1"]


def test_apply_phrase_corrections_estate_terms() -> None:
    phrase_exact = [
        ("bop ashore", "Bob assurer"),
        ("tailscape", "Tailscale"),
        ("con jobs", "cron jobs"),
        ("qwen 3.8", "Qwen 3.5"),
        ("encrypt2 tasks", "crypto tasks"),
        ("no peace to print me", "novice-friendly"),
    ]
    text, _ = apply_phrase_corrections("Agree a solution with bop ashore", phrase_exact, [])
    assert text == "Agree a solution with Bob assurer"

    text2, _ = apply_phrase_corrections("modify apps on phone to use tailscape", phrase_exact, [])
    assert text2 == "modify apps on phone to use Tailscale"

    text3, _ = apply_phrase_corrections("we ran some con jobs for qwen 3.8 and encrypt2 tasks", phrase_exact, [])
    assert text3 == "we ran some cron jobs for Qwen 3.5 and crypto tasks"


def test_apply_phrase_corrections_multiword_order() -> None:
    # Ensure multiword "bob assurer" matches before sub-words "bob" or "assure"
    phrase_exact = [
        ("bob", "Bob"),
        ("assure", "assure"),
        ("bob assure", "Bob assurer"),
        ("kimmy k3", "Kimi-k3"),
    ]
    text, _ = apply_phrase_corrections("let bob assure the implementation with kimmy k3", phrase_exact, [])
    assert text == "let Bob assurer the implementation with Kimi-k3"


def test_dedupe_repeated_ngrams_preserves_clause_boundaries() -> None:
    # "when I've used it, it did search" has a legitimate clause boundary and should not be collapsed
    raw = "when I've used it, it did search the web"
    assert dedupe_repeated_ngrams(raw) == "when I've used it, it did search the web"
    assert post_clean_dedupe(raw) == "when I've used it, it did search the web"

