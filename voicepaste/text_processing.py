import re
from typing import List, Pattern, Sequence, Tuple


def sanitize_model_output(text: str) -> str:
    cleaned = (text or "").replace("\r", "").strip()
    if not cleaned:
        return ""

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if len(lines) > 1:
        first = lines[0].lower()
        if any(tag in first for tag in ("cleaned transcript", "output", "here is", "here's", "rewritten text")):
            lines = lines[1:]
    cleaned = " ".join(lines).strip()

    if cleaned.startswith("**") and cleaned.endswith("**") and len(cleaned) > 4:
        cleaned = cleaned[2:-2].strip()

    cleaned = re.sub(
        r"^\s*(sure!?[, ]*)?(here(?: is|\'s)?\s+)?(?:the\s+)?(?:cleaned\s+transcript|output|rewritten\s+text)\s*:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned


def apply_phrase_corrections(
    text: str,
    phrase_exact: Sequence[Tuple[str, str]],
    phrase_regex: Sequence[Tuple[Pattern[str], str]],
) -> Tuple[str, List[str]]:
    out = text
    applied: List[str] = []

    # Sort exact phrases by length descending so longer multi-word phrases match before individual sub-words
    sorted_exact = sorted(phrase_exact, key=lambda pair: len(pair[0]), reverse=True)

    for wrong, right in sorted_exact:
        pattern = re.compile(r"\b" + re.escape(wrong) + r"\b", re.IGNORECASE)
        out, count = pattern.subn(right, out)
        if count:
            applied.append(f"exact:{wrong}->{right}x{count}")

    for pattern, replacement in phrase_regex:
        out, count = pattern.subn(replacement, out)
        if count:
            applied.append(f"regex:{pattern.pattern}->{replacement}x{count}")

    return out, applied


def _normalize_dedupe_text(text: str) -> str:
    return re.sub(r"[\W_]+", " ", (text or "").lower()).strip()


def _normalize_sentence_spacing(text: str) -> str:
    """
    Insert missing whitespace after sentence-ending punctuation when the next
    token starts immediately (common in raw STT output like "before.It's").
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"([.!?])(?=(?:[\"'(\[])?[A-Z])", r"\1 ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def dedupe_consecutive_sentences(text: str) -> str:
    normalized = _normalize_sentence_spacing(text)
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", normalized) if p.strip()]
    if len(parts) <= 1:
        return normalized

    def sent_tokens(sentence: str) -> List[str]:
        return re.findall(r"[a-z0-9']+", sentence.lower())

    def is_near_duplicate(a: str, b: str) -> bool:
        ta = sent_tokens(a)
        tb = sent_tokens(b)
        if len(ta) < 3 or len(tb) < 3:
            return False
        sa = set(ta)
        sb = set(tb)
        if not sa or not sb:
            return False
        overlap = len(sa & sb) / float(min(len(sa), len(sb)))
        return overlap >= 0.75

    out: List[str] = []
    prev_norm = ""
    for part in parts:
        norm = _normalize_dedupe_text(part)
        if not norm:
            continue
        if norm == prev_norm:
            continue
        if out and is_near_duplicate(out[-1], part):
            if len(part.split()) > len(out[-1].split()):
                out[-1] = part
            prev_norm = _normalize_dedupe_text(out[-1])
            continue
        out.append(part)
        prev_norm = norm
    return " ".join(out).strip()


def dedupe_repeated_ngrams(text: str) -> str:
    tokens = (text or "").split()
    if len(tokens) < 2:
        return (text or "").strip()

    def norm_token(token: str) -> str:
        return re.sub(r"(^\W+|\W+$)", "", token).lower()

    out: List[str] = []
    i = 0
    while i < len(tokens):
        max_n = min(10, (len(tokens) - i) // 2)
        matched_n = 0
        matched_seq: List[str] = []
        for n in range(max_n, 1, -1):
            left = [norm_token(t) for t in tokens[i : i + n]]
            right = [norm_token(t) for t in tokens[i + n : i + (2 * n)]]
            if not left or any(not x for x in left):
                continue
            if left == right:
                matched_n = n
                matched_seq = left
                break

        if matched_n:
            out.extend(tokens[i : i + matched_n])
            i += matched_n
            while i + matched_n <= len(tokens):
                probe = [norm_token(t) for t in tokens[i : i + matched_n]]
                if probe == matched_seq:
                    i += matched_n
                else:
                    break
            continue

        current_norm = norm_token(tokens[i])
        previous_norm = norm_token(out[-1]) if out else ""
        if current_norm and previous_norm and current_norm == previous_norm:
            # Protect legitimate grammatical clause repetitions (e.g. "used it, it did" or "is, is")
            clause_words = {
                "it", "that", "this", "is", "was", "had", "have", "has", "in",
                "what", "he", "she", "we", "they", "you", "i", "do", "did", "all",
            }
            if (
                out
                and re.search(r"[,;:.!?—–-]$", out[-1])
                and not re.search(r"[,;:.!?—–-]$", tokens[i])
                and current_norm in clause_words
            ):
                out.append(tokens[i])
                i += 1
                continue
            i += 1
            continue

        out.append(tokens[i])
        i += 1

    cleaned = " ".join(out)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"\(\s+", "(", cleaned)
    cleaned = re.sub(r"\s+\)", ")", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def post_clean_dedupe(text: str) -> str:
    text = _normalize_sentence_spacing(text)
    if not text:
        return ""
    step1 = dedupe_consecutive_sentences(text)
    step2 = dedupe_repeated_ngrams(step1)
    return step2


def light_post_polish(text: str) -> str:
    out = (text or "").strip()
    if not out:
        return ""

    out = re.sub(r"\b(?:um+|uh+|er+|ah+|hmm+|mmm+|mm+)\b[,.!?]*", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r"\(\s+", "(", out)
    out = re.sub(r"\s+\)", ")", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,")
    if not out:
        return ""

    chars = list(out)
    cap_next = True
    for i, ch in enumerate(chars):
        if cap_next and ch.isalpha():
            chars[i] = ch.upper()
            cap_next = False
        if ch in ".!?":
            cap_next = True
    out = "".join(chars)
    out = re.sub(r"\bi\b", "I", out)
    out = re.sub(r"\s{2,}", " ", out).strip()

    if out and out[-1] not in ".!?":
        out = f"{out}."
    return out
