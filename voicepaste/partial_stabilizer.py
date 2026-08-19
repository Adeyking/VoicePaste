from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple


def _common_prefix_len(left: List[str], right: List[str]) -> int:
    size = min(len(left), len(right))
    idx = 0
    while idx < size and left[idx] == right[idx]:
        idx += 1
    return idx


@dataclass
class PartialTranscriptStabilizer:
    hold_back_words: int = 2
    _stable_tokens: List[str] = field(default_factory=list)
    _last_tokens: List[str] = field(default_factory=list)

    def ingest(self, text: str) -> Tuple[str, str]:
        cleaned = (text or "").strip()
        if not cleaned:
            return "", " ".join(self._stable_tokens).strip()

        tokens = cleaned.split()
        if not self._last_tokens:
            self._last_tokens = tokens
            return cleaned, ""

        common = _common_prefix_len(self._last_tokens, tokens)
        commit_upto = max(0, common - max(0, self.hold_back_words))
        if commit_upto > len(self._stable_tokens):
            self._stable_tokens = tokens[:commit_upto]

        stable_count = len(self._stable_tokens)
        display_tokens = self._stable_tokens + tokens[stable_count:]
        display_text = " ".join(display_tokens).strip()
        stable_text = " ".join(self._stable_tokens).strip()
        self._last_tokens = tokens
        return display_text, stable_text
