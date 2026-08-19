from __future__ import annotations

import re
from typing import List, Tuple


_LITERAL_PATTERNS = (
    "new paragraph",
    "new line",
    "question mark",
    "exclamation mark",
    "period",
    "comma",
    "scratch that",
    "actually",
)


def _clean_spacing(text: str) -> str:
    out = re.sub(r"[ \t]+", " ", text)
    out = re.sub(r" *\n *", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    # Add space after comma/semicolon/exclamation/question mark if followed by a letter (protects callouts like [!NOTE] and numbers like 1,000)
    out = re.sub(r"(?<!\d)(?<!\[)([,;!?])([A-Za-z])", r"\1 \2", out)
    # Add space after sentence-ending punctuation when followed by a capital letter or quote (protects [!NOTE])
    out = re.sub(r"(?<!\[)([.!?])(?=(?:[\"'(\[])?[A-Z])", r"\1 ", out)
    out = re.sub(r"[ \t]+", " ", out)
    return out.strip()


def _apply_backtrack_actually(text: str) -> Tuple[str, bool]:
    lowered = text.lower()
    marker = "actually"
    idx = lowered.find(marker)
    if idx < 0:
        return text, False
    before = text[:idx]
    after = text[idx + len(marker) :]
    cut = max(before.rfind("."), before.rfind("!"), before.rfind("?"), before.rfind("\n"))
    if cut >= 0:
        before = before[: cut + 1]
    else:
        before = ""
    return _clean_spacing(f"{before} {after}"), True


def _apply_backtrack_scratch_that(text: str) -> Tuple[str, bool]:
    lowered = text.lower()
    marker = "scratch that"
    idx = lowered.find(marker)
    if idx < 0:
        return text, False
    before = text[:idx]
    after = text[idx + len(marker) :]
    cut = max(before.rfind("."), before.rfind("!"), before.rfind("?"), before.rfind("\n"))
    if cut >= 0:
        before = before[: cut + 1]
    else:
        before = ""
    return _clean_spacing(f"{before} {after}"), True


def _apply_obsidian_formatting(text: str) -> Tuple[str, List[str]]:
    applied: List[str] = []
    out = text

    callout_pattern = re.compile(
        r"(?:^|\n)\s*(?:insert note callout|note callout|callout note)\b\s*",
        flags=re.IGNORECASE,
    )
    if callout_pattern.search(out):
        out = callout_pattern.sub("> [!NOTE]\n", out)
        applied.append("obsidian:note_callout")

    task_pattern = re.compile(
        r"(?:^|\n)\s*(?:tag task|create task)\s+(.+?)(?=\n|$)",
        flags=re.IGNORECASE,
    )
    out, task_count = task_pattern.subn(r"- [ ] \1", out)
    if task_count:
        applied.append(f"obsidian:tag_task:{task_count}")

    idea_pattern = re.compile(
        r"(?:^|\n)\s*(?:tag idea|create idea)\s+(.+?)(?=\n|$)",
        flags=re.IGNORECASE,
    )
    out, idea_count = idea_pattern.subn(r"- 💡 **Idea**: \1", out)
    if idea_count:
        applied.append(f"obsidian:tag_idea:{idea_count}")

    corr_pattern = re.compile(
        r"(?:^|\s)correct\s+(.+?)\s+(?:to|as)\s+(.+?)(?=[,.;:!?]|\s*$)",
        flags=re.IGNORECASE,
    )
    m = corr_pattern.search(out)
    if m:
        wrong = m.group(1).strip()
        right = m.group(2).strip()
        if wrong and right:
            applied.append(f"add_correction:{wrong}->{right}")
            out = corr_pattern.sub(f"{right}", out)

    return out, applied


def apply_voice_commands(text: str) -> Tuple[str, List[str]]:
    out = (text or "").strip()
    if not out:
        return "", []

    applied: List[str] = []
    literals: dict[str, str] = {}
    for i, phrase in enumerate(_LITERAL_PATTERNS):
        token = f"__VOICE_LITERAL_{i}__"
        pattern = re.compile(rf"\bliteral\s+{re.escape(phrase)}\b", flags=re.IGNORECASE)
        if pattern.search(out):
            out = pattern.sub(token, out)
            literals[token] = phrase
            applied.append(f"literal:{phrase}")

    out, obs_applied = _apply_obsidian_formatting(out)
    applied.extend(obs_applied)

    replacements = [
        (r"\bnew paragraph\b", "\n\n", "new_paragraph"),
        (r"\bnew line\b", "\n", "new_line"),
        (r"\bquestion mark\b", "?", "question_mark"),
        (r"\bexclamation mark\b", "!", "exclamation_mark"),
        (r"\bperiod\b", ".", "period"),
        (r"\bcomma\b", ",", "comma"),
    ]
    for pattern, replacement, label in replacements:
        regex = re.compile(pattern, flags=re.IGNORECASE)
        out, count = regex.subn(replacement, out)
        if count:
            applied.append(f"{label}x{count}")

    out, changed = _apply_backtrack_scratch_that(out)
    if changed:
        applied.append("scratch_that")

    out, changed = _apply_backtrack_actually(out)
    if changed:
        applied.append("actually")

    for token, phrase in literals.items():
        out = out.replace(token, phrase)

    return _clean_spacing(out), applied
