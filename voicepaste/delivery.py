from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import keyboard


def paste_transcript(
    target_hwnd: Any,
    paste_timeout_ms: int,
    set_foreground_window: Callable[[Any], bool],
    increment_error: Callable[[str], None],
    status: Callable[[str, str], None],
    get_foreground_window: Optional[Callable[[], Any]] = None,
    verify_focus: bool = True,
) -> bool:
    if not target_hwnd:
        status("PASTE", "No target window captured; clipboard only.")
        return False

    if verify_focus and get_foreground_window is not None:
        try:
            current_hwnd = get_foreground_window()
            if current_hwnd and current_hwnd != target_hwnd:
                status(
                    "PASTE_GUARD",
                    f"Focus shifted away from target window (captured HWND {target_hwnd} vs current HWND {current_hwnd}); auto-paste suppressed, text kept on clipboard.",
                )
                return False
        except Exception as exc:
            status("PASTE_GUARD", f"Could not verify focus window handle: {exc}")

    deadline = time.monotonic() + (paste_timeout_ms / 1000.0)
    focused = False
    while time.monotonic() < deadline:
        focused = bool(set_foreground_window(target_hwnd))
        if focused:
            break
        time.sleep(0.05)

    if not focused:
        status("ERROR", "Paste failed — could not focus target window.")
        return False

    try:
        time.sleep(0.015)
        keyboard.send("ctrl+v")
        time.sleep(0.010)
        return True

    except Exception as exc:
        increment_error("paste_failures")
        status("ERROR", f"Paste failed: {exc}")
        return False



def append_to_journal(text: str, journal_file_path: str) -> Path:
    file_path = Path(journal_file_path)
    return append_to_transcript_file(
        text=text,
        transcript_file_path=str(file_path),
        tag="voice-journal",
    )


def append_to_transcript_file(
    text: str,
    transcript_file_path: str,
    tag: str = "voice-inbox",
    note_type: str = "log",
) -> Path:
    file_path = Path(transcript_file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    is_new = not file_path.exists() or file_path.stat().st_size == 0
    now = datetime.now()
    today_date = now.strftime("%Y-%m-%d")
    now_time = now.strftime("%Y-%m-%d %H:%M:%S")

    with file_path.open("a", encoding="utf-8") as handle:
        if is_new:
            frontmatter = (
                "---\n"
                f"type: {note_type}\n"
                "status: active\n"
                f"created: {today_date}\n"
                f"updated: {today_date}\n"
                f"tags: [{tag}]\n"
                "---\n\n"
            )
            handle.write(frontmatter)

        handle.write(f"## {now_time}\n")
        handle.write(text.strip() + "\n\n")

    return file_path
