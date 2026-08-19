#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voicepaste import defaults
from voicepaste.curate_vocabulary import curate_vocabulary_from_logs_and_inbox


def main() -> None:
    log_dir = os.path.expandvars(defaults.DEFAULT_LOG_DIR)
    inbox_dir = os.path.expandvars(r"%USERPROFILE%\Documents\VoicePaste\voice_paste\inbox")
    corrections_path = os.path.expandvars(defaults.DEFAULT_PHRASE_CORRECTIONS_PATH)

    print("🔍 Running VoicePaste Spoken Vocabulary Curation...")
    result = curate_vocabulary_from_logs_and_inbox(
        log_dir=log_dir,
        inbox_dir=inbox_dir,
        phrase_corrections_path=corrections_path,
    )

    print(f"📊 Scanned {result['scanned_logs']} log file(s) and {result['scanned_inbox_notes']} inbox note(s).")
    print(f"✨ New word corrections added: {result['new_pairs_added']}")
    if result["added_pairs"]:
        for pair in result["added_pairs"]:
            print(f"   • '{pair['wrong']}' -> '{pair['right']}'")
    print(f"📚 Total active phrase corrections: {result['total_corrections']}")


if __name__ == "__main__":
    main()
