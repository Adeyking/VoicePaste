import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image, ImageDraw, ImageOps
import pystray
from pystray import MenuItem as item

from .engine import PushToTalkClient, VoicePasteConfig, build_parser
from .settings_window import SettingsWindow
from .single_instance import SingleInstanceGuard

APP_NAME = "VoicePaste"
_CONFIG_API_URL = "http://localhost:8766/config"


class TrayHost:
    def __init__(self, client: PushToTalkClient) -> None:
        self.client = client
        self.icon: Optional[pystray.Icon] = None
        self._status_text = "Idle"
        self._settings_thread: Optional[threading.Thread] = None
        self._stt_healthy: bool = True

    def on_status(self, payload: Dict[str, Any]) -> None:
        state = payload.get("state", "STATUS")
        message = payload.get("message", "")
        if state == "HEALTH":
            healthy = message == "online"
            if healthy != self._stt_healthy:
                self._stt_healthy = healthy
                self._update_tray_icon()
            return
        self._status_text = f"{state}: {message}"[:64]
        if self.icon is not None:
            try:
                self.icon.update_menu()
            except Exception:
                pass
            if state in {"ERROR", "REFINE"}:
                try:
                    self.icon.notify(message, APP_NAME)
                except Exception:
                    pass

    def _stats_line(self) -> str:
        stats = self.client.get_stats()
        return (
            f"Stats: u={stats['utterances_completed']}/{stats['utterances_total']} "
            f"stt={stats['avg_stt_ms']}ms clean={stats['avg_cleanup_ms']}ms "
            f"up={stats['uptime_s']}s"
        )

    def _hotkeys_menu(self) -> pystray.Menu:
        keys = self.client.get_hotkey_bindings()
        return pystray.Menu(
            item(lambda _: f"Push-to-talk: {keys['ptt']}", None, enabled=False),
            item(
                lambda _: (
                    f"Mode: {keys['mode_dictation']}/{keys['mode_assistant']}/"
                    f"{keys['mode_journal']}/{keys['mode_meeting']}"
                ),
                None,
                enabled=False,
            ),
            item(
                lambda _: (
                    f"Profiles: {keys['profile_email']}/{keys['profile_chat']}/{keys['profile_neutral']}"
                ),
                None,
                enabled=False,
            ),
            item(
                lambda _: f"Models: {keys['model_fast']}/{keys['model_quality']}",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            # Item 10: voice commands discoverability
            item("  \u2014 Voice Commands —", None, enabled=False),
            item('  "new paragraph" → blank line', None, enabled=False),
            item('  "new line" → line break', None, enabled=False),
            item('  "scratch that" → delete last sentence', None, enabled=False),
            item('  "actually" → delete last sentence', None, enabled=False),
            item(
                '  "question mark" / "period" / "comma" → punctuation',
                None,
                enabled=False,
            ),
            item('  "literal [cmd]" → insert phrase verbatim', None, enabled=False),
        )

    def _create_image(self) -> Image.Image:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        draw.rounded_rectangle((4, 4, 60, 60), radius=14, fill="#0f4c5c")
        draw.rounded_rectangle((10, 10, 54, 54), radius=12, fill="#2a9d8f")

        # Mic capsule
        draw.rounded_rectangle((23, 13, 41, 34), radius=9, fill="#f4f1de")
        draw.rounded_rectangle((26, 16, 38, 31), radius=6, fill="#e9c46a")
        # Stem/base
        draw.rectangle((30, 34, 34, 46), fill="#f4f1de")
        draw.arc((19, 34, 45, 56), start=205, end=-25, fill="#f4f1de", width=3)
        draw.rounded_rectangle((24, 51, 40, 55), radius=2, fill="#f4f1de")
        # Sound bars
        draw.rounded_rectangle((12, 22, 15, 34), radius=1, fill="#ffffff")
        draw.rounded_rectangle((49, 22, 52, 34), radius=1, fill="#ffffff")
        return image

    def _create_image_offline(self) -> Image.Image:
        """Greyscale version of the normal icon, used when NucBox STT is unreachable."""
        base = self._create_image()
        r, g, b, a = base.split()
        grey = ImageOps.grayscale(Image.merge("RGB", (r, g, b))).convert("RGB")
        return Image.merge("RGBA", (*grey.split(), a))

    def _update_tray_icon(self) -> None:
        if self.icon is None:
            return
        try:
            self.icon.icon = (
                self._create_image() if self._stt_healthy else self._create_image_offline()
            )
        except Exception:
            pass

    def _post_config(self, updates: Dict[str, Any]) -> None:
        """Fire-and-forget POST of ``updates`` to the Config API.

        Runs in a daemon thread so menu callbacks never block.  Errors are
        logged at WARNING level but are never raised — the Config API may not be
        reachable in CLI mode or during testing.
        """
        def _do_post() -> None:
            try:
                body = json.dumps(updates).encode("utf-8")
                req = urllib.request.Request(
                    _CONFIG_API_URL,
                    data=body,
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=2).close()
            except Exception as exc:
                logging.getLogger("voicepaste").warning(
                    "Config API POST failed %s: %s", updates, exc
                )

        threading.Thread(target=_do_post, daemon=True, name="cfg-api-post").start()

    def _start_config_watcher(self) -> None:
        """Start background thread that watches the config file for external changes."""
        t = threading.Thread(
            target=self._config_watcher_loop, daemon=True, name="cfg-watcher"
        )
        t.start()

    def _config_watcher_loop(self) -> None:
        """Poll config file every 5 s; apply MODE_DEFAULT and MODEL_PROFILE if changed externally."""
        config_path = self.client.config.config_path
        log = logging.getLogger("voicepaste")
        try:
            last_mtime = config_path.stat().st_mtime
        except OSError:
            last_mtime = 0.0

        while True:
            time.sleep(5)
            try:
                mtime = config_path.stat().st_mtime
            except OSError:
                continue
            if mtime == last_mtime:
                continue
            last_mtime = mtime
            try:
                raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue

            changed = False

            new_mode = str(raw.get("MODE_DEFAULT", "")).strip().lower()
            if new_mode and new_mode != self.client.get_mode():
                self.client.set_mode(new_mode, announce=False)
                log.info("[CONFIG-WATCH] Mode applied from config file: %s", new_mode)
                changed = True

            new_profile = str(raw.get("MODEL_PROFILE", "")).strip().lower()
            if new_profile and new_profile != self.client.get_model_profile():
                self.client.set_model_profile(new_profile, persist=False)
                log.info("[CONFIG-WATCH] Profile applied from config file: %s", new_profile)
                changed = True

            if changed and self.icon is not None:
                try:
                    self.icon.update_menu()
                except Exception:
                    pass

    def _open_logs(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        os.startfile(str(self.client.logger_dir))

    def _open_corrections(self) -> None:
        path = self.client.config.phrase_corrections_path_expanded()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text('{\n  "exact": {},\n  "regex": []\n}\n', encoding="utf-8")
        os.startfile(str(path))

    def _open_snippets(self) -> None:
        path = self.client.config.snippets_path_expanded()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text('{\n  "exact": {}\n}\n', encoding="utf-8")
        os.startfile(str(path))

    def _open_settings(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        if self._settings_thread and self._settings_thread.is_alive():
            return

        def run_settings() -> None:
            dialog = SettingsWindow(
                self.client.config,
                on_save=self._save_settings,
                on_edit_corrections=self._open_corrections,
                on_edit_snippets=self._open_snippets,
            )
            dialog.run()

        self._settings_thread = threading.Thread(target=run_settings, daemon=True)
        self._settings_thread.start()

    def _save_settings(self, updates: Dict[str, Any]) -> None:
        self.client.update_runtime_config(updates, persist=False)
        self._post_config(updates)
        if "MODEL_PROFILE" in updates:
            self.client.warm_selected_model_now(background=True)
        if self.icon is not None:
            self.icon.update_menu()

    def _toggle_listening(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        if self.client.is_listening():
            self.client.stop_listening()
            msg = "Listening paused."
        else:
            self.client.start_listening()
            msg = "Listening enabled."
        if self.icon is not None:
            self.icon.update_menu()
            try:
                self.icon.notify(msg, APP_NAME)
            except Exception:
                pass

    def _set_profile(self, profile: str) -> None:
        self.client.set_model_profile(profile, persist=False)
        self._post_config({"MODEL_PROFILE": profile})
        if self.icon is not None:
            self.icon.update_menu()
            try:
                self.icon.notify(f"Model set to {profile}.", APP_NAME)
            except Exception:
                pass

    def _set_mode(self, mode: str) -> None:
        self.client.set_mode(mode, persist=False)
        self._post_config({"MODE_DEFAULT": mode})
        if self.icon is not None:
            self.icon.update_menu()
            try:
                self.icon.notify(f"Mode set to {mode}.", APP_NAME)
            except Exception:
                pass

    def _set_assistant_profile(self, profile: str) -> None:
        self.client.set_assistant_profile(profile)
        self._post_config({"ASSISTANT_PROFILE": profile})
        if self.icon is not None:
            self.icon.update_menu()

    def _assistant_profile_menu(self) -> pystray.Menu:
        return pystray.Menu(
            item(
                "Neutral",
                lambda _icon, _it: self._set_assistant_profile("neutral"),
                checked=lambda _: self.client.get_assistant_profile() == "neutral",
            ),
            item(
                "Email",
                lambda _icon, _it: self._set_assistant_profile("email"),
                checked=lambda _: self.client.get_assistant_profile() == "email",
            ),
            item(
                "Chat",
                lambda _icon, _it: self._set_assistant_profile("chat"),
                checked=lambda _: self.client.get_assistant_profile() == "chat",
            ),
        )

    def _mode_menu(self) -> pystray.Menu:
        return pystray.Menu(
            item(
                "Dictation",
                lambda _icon, _it: self._set_mode("dictation"),
                checked=lambda _: self.client.get_mode() == "dictation",
            ),
            item(
                "Assistant",
                lambda _icon, _it: self._set_mode("assistant"),
                checked=lambda _: self.client.get_mode() == "assistant",
            ),
            item(
                "Journal",
                lambda _icon, _it: self._set_mode("journal"),
                checked=lambda _: self.client.get_mode() == "journal",
            ),
            item(
                "Meeting",
                lambda _icon, _it: self._set_mode("meeting"),
                checked=lambda _: self.client.get_mode() == "meeting",
            ),
        )

    def _set_stt_provider(self, provider: str) -> None:
        use_cloud = (provider == "cloud")
        self.client.set_cloud_fallback_enabled(use_cloud, persist=True)
        self._post_config({"CLOUD_FALLBACK_ENABLED": use_cloud})
        if self.icon is not None:
            self.icon.update_menu()
            try:
                label = "Cloud Gemini Free Tier" if use_cloud else "Local Whisper (Port 8770)"
                self.icon.notify(f"STT Provider set to {label}.", APP_NAME)
            except Exception:
                pass

    def _provider_menu(self) -> pystray.Menu:
        return pystray.Menu(
            item(
                "Local Whisper (NucBox Port 8770)",
                lambda icon, it: self._set_stt_provider("local"),
                checked=lambda _: not self.client.get_cloud_fallback_enabled(),
            ),
            item(
                "Cloud Gemini Free Tier",
                lambda icon, it: self._set_stt_provider("cloud"),
                checked=lambda _: self.client.get_cloud_fallback_enabled(),
            ),
        )

    def _dictation_mode_menu(self) -> pystray.Menu:
        return pystray.Menu(
            item(
                "Verbatim (Fast Raw Speech)",
                lambda icon, it: self._set_profile("verbatim"),
                checked=lambda _: self.client.get_model_profile() == "verbatim",
            ),
            item(
                "Polish Mode (Grammar Cleanup)",
                lambda icon, it: self._set_profile("quality"),
                checked=lambda _: self.client.get_model_profile() in {"quality", "fast"},
            ),
        )

    def _model_menu(self) -> pystray.Menu:
        return self._dictation_mode_menu()

    def _meeting_menu(self) -> pystray.Menu:
        return pystray.Menu(
            item(
                "Start Session",
                self._start_meeting_session,
                enabled=lambda _: not self.client.is_meeting_session_active(),
            ),
            item(
                "Stop Session",
                self._stop_meeting_session,
                enabled=lambda _: self.client.is_meeting_session_active(),
            ),
        )

    def _curate_vocabulary(self, _icon: Any = None, _item: Any = None) -> None:
        def _worker() -> None:
            from .curate_vocabulary import curate_vocabulary_from_logs_and_inbox
            from .engine import _expand_path
            log_dir = Path(_expand_path(self.client.config.log_dir))
            inbox_dir = self.client.config.voice_paste_root_path() / "inbox"
            corrections_path = self.client.config.phrase_corrections_path_expanded()
            result = curate_vocabulary_from_logs_and_inbox(
                log_dir=log_dir,
                inbox_dir=inbox_dir,
                phrase_corrections_path=corrections_path,
            )
            n_added = result.get("new_pairs_added", 0)
            msg = (
                f"Curated vocabulary: {n_added} new correction(s) added."
                if n_added > 0
                else "Curated vocabulary: No new unmapped corrections found."
            )
            if self.icon is not None:
                self.icon.notify(msg, APP_NAME)

        threading.Thread(target=_worker, daemon=True).start()

    def _open_menu(self) -> pystray.Menu:
        return pystray.Menu(
            item("Settings", self._open_settings),
            item("Logs", self._open_logs),
            item("Corrections", lambda _icon, _item: self._open_corrections()),
            item("Snippets", lambda _icon, _item: self._open_snippets()),
            item("Curate Vocabulary", self._curate_vocabulary),
        )

    def _start_meeting_session(
        self, _icon: pystray.Icon, _item: pystray.MenuItem
    ) -> None:
        self.client.start_meeting_session()
        if self.icon is not None:
            self.icon.update_menu()

    def _stop_meeting_session(
        self, _icon: pystray.Icon, _item: pystray.MenuItem
    ) -> None:
        self.client.stop_meeting_session()
        if self.icon is not None:
            self.icon.update_menu()

    def _exit(self, icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self.client.shutdown()
        icon.stop()

    def _toggle_hud(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        new_val = not self.client.is_hud_enabled()
        self.client.set_hud_enabled(new_val)
        if self.icon is not None:
            self.icon.update_menu()

    def run(self) -> None:
        menu = pystray.Menu(
            # ── Status ───────────────────────────────────────────────
            item(lambda _: f"● {self._status_text}", None, enabled=False),
            item(lambda _: self._stats_line(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            # ── Pure Core Dictation Controls ──────────────────────────
            item(
                "Listening Active",
                self._toggle_listening,
                checked=lambda _: self.client.is_listening(),
            ),
            item("Dictation Profile", self._dictation_mode_menu()),
            item("STT Provider", self._provider_menu()),
            item(
                "Floating Status HUD",
                self._toggle_hud,
                checked=lambda _: self.client.is_hud_enabled(),
            ),
            item("Open Logs & Config", self._open_menu()),
            pystray.Menu.SEPARATOR,
            item("Exit VoicePaste", self._exit),
        )
        initial_image = (
            self._create_image() if self._stt_healthy else self._create_image_offline()
        )
        self.icon = pystray.Icon(
            "voice_translator", initial_image, APP_NAME, menu
        )
        self._start_config_watcher()
        self.icon.run()


def _setup_logging() -> None:
    """Configure a rotating file handler for the voicepaste logger.

    Uses logs/voicepaste.log relative to the project root (same directory as the
    existing daily log files).  Rotates at 1 MB, keeps 3 backups.  stdout is left
    untouched so the logger does not interfere with CLI mode.
    """
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "voicepaste.log"

    handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("voicepaste")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        logger.addHandler(handler)
    logger.propagate = False


def main() -> None:
    _setup_logging()

    guard = SingleInstanceGuard()
    try:
        guard.acquire()
    except RuntimeError as exc:
        # Another live instance holds the lock — log the reason so subsequent
        # silent exits are traceable, then os._exit to bypass any background
        # threads that would otherwise keep the dead process idling at 0 CPU.
        logging.getLogger("voicepaste").warning(
            "Exiting: single-instance lock held (%s). Lock file: %s",
            exc,
            guard.lock_path,
        )
        import os as _os
        _os._exit(0)

    if guard.last_stale_pid is not None:
        # Previous instance crashed without releasing the lock; we cleaned it up.
        logging.getLogger("voicepaste").info(
            "Reclaimed stale single-instance lock (previous pid=%s).",
            guard.last_stale_pid,
        )

    parser = build_parser()
    try:
        args = parser.parse_args()
    except SystemExit as exc:
        guard.release()
        raise exc

    if getattr(args, "version", False):
        from .version import __version__

        print(f"VoicePaste {__version__}")
        guard.release()
        return
    try:
        config = VoicePasteConfig.load(args)
        config.app_mode = "tray"

        host: Optional[TrayHost] = None

        def on_status(payload: Dict[str, Any]) -> None:
            if host is not None:
                host.on_status(payload)

        host_client = PushToTalkClient(config, status_callback=on_status)

        # Restore assistant profile from the config file so a dashboard change
        # survives a tray restart.  The engine hardcodes "neutral" in __init__,
        # so we apply the persisted value here before startup() runs.
        try:
            _raw_cfg = json.loads(
                config.config_path.read_text(encoding="utf-8-sig")
            )
            _ap = str(_raw_cfg.get("ASSISTANT_PROFILE", "")).strip().lower()
            if _ap in ("neutral", "email", "chat"):
                host_client.set_assistant_profile(_ap, announce=False)
        except Exception:
            pass  # file missing or malformed — keep default "neutral"

        host = TrayHost(host_client)
        host_client.startup()
        host_client.install_keyboard_hooks()

        try:
            import sys
            _vp_root = Path(__file__).resolve().parent.parent
            if str(_vp_root) not in sys.path:
                sys.path.insert(0, str(_vp_root))
            import voicepaste_config_api
            _api_thread = threading.Thread(
                target=voicepaste_config_api.run_api_server, daemon=True
            )
            _api_thread.start()
        except Exception:
            pass

        host.run()
    finally:
        guard.release()


if __name__ == "__main__":
    main()

