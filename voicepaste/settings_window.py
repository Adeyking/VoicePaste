import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import urlparse
from typing import Any, Callable, Dict, Optional

import requests

from . import defaults
from .engine import VoicePasteConfig

APP_NAME = "VoicePaste"


class SettingsWindow:
    def __init__(
        self,
        config: VoicePasteConfig,
        on_save: Callable[[Dict[str, Any]], None],
        on_edit_corrections: Callable[[], None],
        on_edit_snippets: Optional[Callable[[], None]] = None,
    ) -> None:
        self._config = config
        self._on_save = on_save
        self._on_edit_corrections = on_edit_corrections
        self._on_edit_snippets = on_edit_snippets or (lambda: None)

    def run(self) -> None:
        root = tk.Tk()
        root.title(f"{APP_NAME} Settings")
        root.resizable(True, True)

        vars_map = {
            "stt_url": tk.StringVar(value=self._config.stt_url),
            "ollama_url": tk.StringVar(value=self._config.ollama_url),
            "model_profile": tk.StringVar(value=self._config.model_profile),
            "mode_default": tk.StringVar(value=self._config.mode_default),
            "voice_paste_root": tk.StringVar(value=self._config.voice_paste_root),
            "ollama_keep_alive": tk.StringVar(value=self._config.ollama_keep_alive),
            "cloud_fallback_enabled": tk.BooleanVar(
                value=self._config.cloud_fallback_enabled
            ),
            "phrase_corrections_path": tk.StringVar(
                value=self._config.phrase_corrections_path
            ),
            "journal_path": tk.StringVar(value=self._config.journal_path),
            "meeting_paste": tk.BooleanVar(value=self._config.meeting_paste),
            "audio_feedback": tk.BooleanVar(value=self._config.audio_feedback),
            "partial_transcript_enabled": tk.BooleanVar(
                value=self._config.partial_transcript_enabled
            ),
            "partial_update_interval_ms": tk.StringVar(
                value=str(self._config.partial_update_interval_ms)
            ),
            "smart_formatting_enabled": tk.BooleanVar(
                value=self._config.smart_formatting_enabled
            ),
            "voice_commands_enabled": tk.BooleanVar(
                value=self._config.voice_commands_enabled
            ),
            "meeting_session_chunk_seconds": tk.StringVar(
                value=str(self._config.meeting_session_chunk_seconds)
            ),
            "snippets_path": tk.StringVar(value=self._config.snippets_path),
            "warmup_enabled": tk.BooleanVar(value=self._config.warmup_enabled),
        }

        # Resolved model name label — updates when Model Profile changes
        def _resolved_model_name(profile: str) -> str:
            if profile == "fast":
                return self._config.fast_model
            if profile == "quality":
                return self._config.quality_model
            return ""

        resolved_model_var = tk.StringVar(
            value=f"→ {_resolved_model_name(self._config.model_profile)}"
        )

        def _on_profile_change(*_: object) -> None:
            resolved_model_var.set(
                f"→ {_resolved_model_name(vars_map['model_profile'].get())}"
            )

        vars_map["model_profile"].trace_add("write", _on_profile_change)

        # ── Scrollable container ──────────────────────────────────────
        canvas = tk.Canvas(root, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
        outer_frame = ttk.Frame(canvas)
        outer_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=outer_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.bind_all(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )

        # ── Layout helpers ────────────────────────────────────────────
        PAD = dict(padx=8, pady=4)

        def make_section(title: str) -> ttk.LabelFrame:
            f = ttk.LabelFrame(outer_frame, text=title, padding=(8, 4))
            f.pack(fill=tk.X, padx=10, pady=6, anchor="w")
            return f

        def add_entry(frame: tk.Widget, row: int, label: str, key: str) -> None:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", **PAD)
            ttk.Entry(frame, textvariable=vars_map[key], width=52).grid(
                row=row, column=1, sticky="w", **PAD
            )

        def add_check(frame: tk.Widget, row: int, label: str, key: str) -> None:
            ttk.Checkbutton(frame, text=label, variable=vars_map[key]).grid(
                row=row, column=0, columnspan=2, sticky="w", **PAD
            )

        def add_combobox(
            frame: tk.Widget, row: int, label: str, key: str, options: list
        ) -> None:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", **PAD)
            ttk.Combobox(
                frame,
                textvariable=vars_map[key],
                values=options,
                state="readonly",
                width=20,
            ).grid(row=row, column=1, sticky="w", **PAD)

        # ── Services ──────────────────────────────────────────────────
        svc = make_section("Services")
        add_entry(svc, 0, "STT URL", "stt_url")
        add_entry(svc, 1, "Ollama URL", "ollama_url")
        add_entry(svc, 2, "Ollama Keep Alive", "ollama_keep_alive")

        # ── Defaults ──────────────────────────────────────────────────
        dfl = make_section("Defaults")
        add_combobox(dfl, 0, "Model Profile", "model_profile", ["verbatim", "fast", "quality"])
        # Item 9: show the resolved Ollama model name next to the dropdown
        ttk.Label(dfl, textvariable=resolved_model_var, foreground="#555").grid(
            row=0, column=2, sticky="w", padx=(0, 8), pady=4
        )
        add_combobox(
            dfl,
            1,
            "Default Mode",
            "mode_default",
            ["dictation", "assistant", "journal", "meeting"],
        )
        # Item 8: expose warmup_enabled so users understand auto-warm can be toggled
        add_check(dfl, 2, "Auto-warm model on selection", "warmup_enabled")

        # ── Paths ─────────────────────────────────────────────────────
        pth = make_section("Paths")
        add_entry(pth, 0, "Voice Paste Root", "voice_paste_root")
        add_entry(pth, 1, "Phrase Corrections", "phrase_corrections_path")
        add_entry(pth, 2, "Snippets", "snippets_path")
        add_entry(pth, 3, "Journal Folder (legacy)", "journal_path")

        # ── Features ─────────────────────────────────────────────────
        ftr = make_section("Features")
        add_check(
            ftr,
            0,
            "Cloud fallback (assistant / journal only)",
            "cloud_fallback_enabled",
        )
        add_check(ftr, 1, "Audio feedback beeps", "audio_feedback")
        add_check(ftr, 2, "Partial transcript preview", "partial_transcript_enabled")
        add_entry(
            ftr, 3, "  Partial update interval (ms)", "partial_update_interval_ms"
        )
        add_check(ftr, 4, "Smart formatting", "smart_formatting_enabled")
        add_check(ftr, 5, "Voice commands", "voice_commands_enabled")

        # ── Meeting ───────────────────────────────────────────────────
        mtg = make_section("Meeting")
        add_check(mtg, 0, "Auto-paste in meeting mode", "meeting_paste")
        add_entry(mtg, 1, "Chunk size (seconds)", "meeting_session_chunk_seconds")

        # ── Action functions ──────────────────────────────────────────
        def reset_defaults() -> None:
            vars_map["model_profile"].set("fast")
            vars_map["mode_default"].set("dictation")
            vars_map["voice_paste_root"].set(defaults.DEFAULT_VOICE_PASTE_ROOT)
            vars_map["ollama_keep_alive"].set("20m")
            vars_map["cloud_fallback_enabled"].set(False)
            vars_map["meeting_paste"].set(False)
            vars_map["audio_feedback"].set(True)
            vars_map["partial_transcript_enabled"].set(True)
            vars_map["partial_update_interval_ms"].set("400")
            vars_map["smart_formatting_enabled"].set(True)
            vars_map["voice_commands_enabled"].set(True)
            vars_map["meeting_session_chunk_seconds"].set("20")
            vars_map["snippets_path"].set(defaults.DEFAULT_SNIPPETS_PATH)
            vars_map["warmup_enabled"].set(True)
            messagebox.showinfo(APP_NAME, "Defaults restored (review and Save).")

        def save() -> None:
            try:
                updates: Dict[str, Any] = {
                    "STT_URL": vars_map["stt_url"].get().strip(),
                    "OLLAMA_URL": vars_map["ollama_url"].get().strip(),
                    "MODEL_PROFILE": vars_map["model_profile"].get().strip().lower(),
                    "MODE_DEFAULT": vars_map["mode_default"].get().strip().lower(),
                    "VOICE_PASTE_ROOT": vars_map["voice_paste_root"].get().strip(),
                    "OLLAMA_KEEP_ALIVE": vars_map["ollama_keep_alive"].get().strip(),
                    "CLOUD_FALLBACK_ENABLED": bool(
                        vars_map["cloud_fallback_enabled"].get()
                    ),
                    "PHRASE_CORRECTIONS_PATH": vars_map["phrase_corrections_path"]
                    .get()
                    .strip(),
                    "JOURNAL_PATH": vars_map["journal_path"].get().strip(),
                    "MEETING_PASTE": bool(vars_map["meeting_paste"].get()),
                    "AUDIO_FEEDBACK": bool(vars_map["audio_feedback"].get()),
                    "PARTIAL_TRANSCRIPT_ENABLED": bool(
                        vars_map["partial_transcript_enabled"].get()
                    ),
                    "PARTIAL_UPDATE_INTERVAL_MS": int(
                        vars_map["partial_update_interval_ms"].get().strip()
                    ),
                    "SMART_FORMATTING_ENABLED": bool(
                        vars_map["smart_formatting_enabled"].get()
                    ),
                    "VOICE_COMMANDS_ENABLED": bool(
                        vars_map["voice_commands_enabled"].get()
                    ),
                    "MEETING_SESSION_CHUNK_SECONDS": int(
                        vars_map["meeting_session_chunk_seconds"].get().strip()
                    ),
                    "SNIPPETS_PATH": vars_map["snippets_path"].get().strip(),
                    "WARMUP_ENABLED": bool(vars_map["warmup_enabled"].get()),
                }
                self._validate_settings(updates)
                self._on_save(updates)
                messagebox.showinfo(APP_NAME, "Settings saved.")
            except Exception as exc:
                messagebox.showerror(APP_NAME, f"Could not save settings: {exc}")

        # ── Buttons ───────────────────────────────────────────────────
        ttk.Separator(outer_frame, orient="horizontal").pack(
            fill=tk.X, padx=10, pady=(8, 0)
        )

        # Secondary actions row
        row_secondary = ttk.Frame(outer_frame)
        row_secondary.pack(fill=tk.X, padx=10, pady=(8, 2))
        ttk.Button(
            row_secondary,
            text="Edit Corrections",
            width=16,
            command=self._on_edit_corrections,
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            row_secondary,
            text="Edit Snippets",
            width=14,
            command=self._on_edit_snippets,
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            row_secondary, text="Reset Defaults", width=14, command=reset_defaults
        ).pack(side=tk.LEFT)

        # Primary actions row
        row_primary = ttk.Frame(outer_frame)
        row_primary.pack(fill=tk.X, padx=10, pady=(4, 14))
        ttk.Button(row_primary, text="Close", width=10, command=root.destroy).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(row_primary, text="Save", width=12, command=save).pack(side=tk.RIGHT)

        root.geometry("700x540")
        root.mainloop()

    def _validate_settings(self, updates: Dict[str, Any]) -> None:
        stt_url = str(updates.get("STT_URL") or "").strip()
        ollama_url = str(updates.get("OLLAMA_URL") or "").strip()
        voice_paste_root = str(updates.get("VOICE_PASTE_ROOT") or "").strip()
        snippets_path = str(
            updates.get("SNIPPETS_PATH")
            or getattr(self._config, "snippets_path", defaults.DEFAULT_SNIPPETS_PATH)
        ).strip()
        partial_update_interval_ms = int(
            updates.get("PARTIAL_UPDATE_INTERVAL_MS")
            or getattr(
                self._config,
                "partial_update_interval_ms",
                defaults.DEFAULT_PARTIAL_UPDATE_INTERVAL_MS,
            )
        )
        meeting_chunk_seconds = int(
            updates.get("MEETING_SESSION_CHUNK_SECONDS")
            or getattr(
                self._config,
                "meeting_session_chunk_seconds",
                defaults.DEFAULT_MEETING_SESSION_CHUNK_SECONDS,
            )
        )

        self._validate_http_url("STT URL", stt_url)
        self._validate_http_url("Ollama URL", ollama_url)
        if not voice_paste_root:
            raise ValueError("Voice Paste Root Folder cannot be empty.")
        if not snippets_path:
            raise ValueError("Snippets Path cannot be empty.")
        if partial_update_interval_ms < 100:
            raise ValueError("Partial Update Interval must be >= 100 ms.")
        if meeting_chunk_seconds < 5:
            raise ValueError("Meeting Chunk Seconds must be >= 5.")

        stt_health = stt_url.rstrip("/")
        if stt_health.endswith("/transcribe"):
            stt_health = stt_health[: -len("/transcribe")] + "/health"
        else:
            stt_health = stt_health + "/health"
        ollama_health = ollama_url.rstrip("/") + "/api/version"

        try:
            self._validate_reachable("STT health", stt_health, timeout_s=2.0)
            self._validate_reachable("Ollama", ollama_health, timeout_s=2.0)
        except ValueError as exc:
            if not messagebox.askyesno(
                APP_NAME,
                f"Warning: {exc}\n\nSave anyway?",
                icon="warning",
            ):
                raise ValueError("Save cancelled.") from exc

    def _validate_http_url(self, label: str, value: str) -> None:
        if not value:
            raise ValueError(f"{label} cannot be empty.")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{label} must be a valid http(s) URL.")

    def _validate_reachable(self, label: str, url: str, timeout_s: float) -> None:
        try:
            response = requests.get(url, timeout=timeout_s)
            if response.status_code >= 400:
                raise ValueError(
                    f"{label} is not reachable (HTTP {response.status_code})."
                )
        except requests.RequestException as exc:
            raise ValueError(f"{label} is not reachable: {exc}") from exc
