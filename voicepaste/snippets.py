from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


def load_snippets(snippets_path: Path) -> List[Tuple[str, str]]:
    if not snippets_path.exists():
        snippets_path.parent.mkdir(parents=True, exist_ok=True)
        snippets_path.write_text('{\n  "exact": {}\n}\n', encoding="utf-8")

    try:
        payload = json.loads(snippets_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(payload, dict):
        return []

    exact = payload.get("exact", {})
    if not isinstance(exact, dict):
        return []

    pairs: List[Tuple[str, str]] = []
    for trigger, expansion in exact.items():
        t = str(trigger).strip()
        e = str(expansion).strip()
        if t and e:
            pairs.append((t, e))
    return pairs


def apply_snippets(text: str, snippets: Sequence[Tuple[str, str]]) -> Tuple[str, List[str]]:
    out = text or ""
    applied: List[str] = []
    for trigger, expansion in snippets:
        pattern = re.compile(rf"(?<![\w-]){re.escape(trigger)}(?![\w-])", flags=re.IGNORECASE)
        out, count = pattern.subn(expansion, out)
        if count:
            applied.append(f"{trigger}->{expansion}x{count}")
    return out, applied
