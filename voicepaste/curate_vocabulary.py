from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Set


def curate_vocabulary_from_logs_and_inbox(
    log_dir: Path | str,
    inbox_dir: Path | str,
    phrase_corrections_path: Path | str,
) -> Dict[str, Any]:
    log_path = Path(log_dir)
    inbox_path = Path(inbox_dir)
    corrections_file = Path(phrase_corrections_path)

    # 1. Load existing phrase corrections
    existing_data: Dict[str, Any] = {"exact": {}, "regex": []}
    if corrections_file.exists():
        try:
            with corrections_file.open("r", encoding="utf-8") as h:
                loaded = json.load(h)
                if isinstance(loaded, dict):
                    existing_data = loaded
        except Exception:
            pass

    exact_map: Dict[str, str] = existing_data.setdefault("exact", {})
    existing_keys: Set[str] = {k.lower().strip() for k in exact_map.keys()}

    scanned_logs = 0
    scanned_inbox_notes = 0
    new_pairs: List[Dict[str, str]] = []

    STOP_WORDS = {
        "a", "an", "the", "to", "in", "on", "of", "and", "or", "is", "it", "at", "by",
        "for", "with", "as", "be", "do", "we", "he", "she", "me", "my", "so", "if", "no",
        "up", "all", "out", "how", "why", "who", "what", "when", "where", "can", "may",
        "post", "get", "put", "delete", "http", "https", "url", "uri", "html", "json",
    }

    # Helper to add a candidate correction
    def add_candidate(wrong: str, right: str) -> None:
        w_clean = wrong.strip()
        r_clean = right.strip()
        if not w_clean or not r_clean or w_clean == r_clean:
            return
        if len(w_clean) < 2 or len(r_clean) < 2:
            return
        key = w_clean.lower()
        if key in STOP_WORDS and key == r_clean.lower():
            return
        if key not in existing_keys:
            exact_map[key] = r_clean
            existing_keys.add(key)
            new_pairs.append({"wrong": key, "right": r_clean})

    # 2. Scan log files
    if log_path.exists() and log_path.is_dir():
        log_files = list(log_path.glob("voicepaste-*.log"))
        scanned_logs = len(log_files)
        for log_file in log_files:
            try:
                with log_file.open("r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if "EVENT" in line and "stt_text_raw" in line:
                            match = re.search(r"EVENT\s+(\{.*\})", line)
                            if match:
                                try:
                                    evt = json.loads(match.group(1))
                                    raw = str(evt.get("stt_text_raw", "")).strip()
                                    corrected = str(evt.get("stt_text_corrected", "")).strip()

                                    # Check spoken correction triggers ("correct [X] to [Y]")
                                    spoken_match = re.search(
                                        r"\bcorrect\s+(.+?)\s+to\s+(.+)\b",
                                        raw,
                                        re.IGNORECASE,
                                    )
                                    if spoken_match:
                                        add_candidate(spoken_match.group(1), spoken_match.group(2))

                                    # Check raw vs corrected diffs (strictly for casing / capitalization of proper nouns)
                                    if raw and corrected and raw != corrected:
                                        raw_words = raw.split()
                                        corr_words = corrected.split()
                                        if len(raw_words) == len(corr_words):
                                            for rw, cw in zip(raw_words, corr_words):
                                                rw_clean = re.sub(r"[^\w]", "", rw)
                                                cw_clean = re.sub(r"[^\w]", "", cw)
                                                if (
                                                    rw_clean
                                                    and cw_clean
                                                    and rw_clean.lower() == cw_clean.lower()
                                                    and rw_clean != cw_clean
                                                ):
                                                    add_candidate(rw_clean.lower(), cw_clean)
                                except Exception:
                                    pass
            except Exception:
                pass

    # 3. Scan inbox files for proper nouns / tech terms
    if inbox_path.exists() and inbox_path.is_dir():
        inbox_files = list(inbox_path.glob("**/*.md"))
        scanned_inbox_notes = len(inbox_files)
        # Extract common tech terms & proper nouns (CamelCase, acronyms)
        tech_term_pattern = re.compile(r"\b([A-Z][a-z0-9]+[A-Z][a-zA-Z0-9]*|[A-Z]{3,})\b")
        for md_file in inbox_files:
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                matches = tech_term_pattern.findall(content)
                for term in set(matches):
                    # Check common lowercase mishearings of proper nouns
                    add_candidate(term.lower(), term)
            except Exception:
                pass

    # 4. Save updated corrections if new pairs found
    if new_pairs:
        corrections_file.parent.mkdir(parents=True, exist_ok=True)
        with corrections_file.open("w", encoding="utf-8") as h:
            json.dump(existing_data, h, indent=2)

    return {
        "scanned_logs": scanned_logs,
        "scanned_inbox_notes": scanned_inbox_notes,
        "new_pairs_added": len(new_pairs),
        "added_pairs": new_pairs,
        "total_corrections": len(exact_map),
    }
