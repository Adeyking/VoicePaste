from __future__ import annotations

import sys
import time
import threading
import tkinter as tk
from typing import Optional, Tuple, Dict, Any

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    GWL_EXSTYLE = -20
    WS_EX_NOACTIVATE = 0x08000000
    WS_EX_TOPMOST = 0x00000008
    WS_EX_TOOLWINDOW = 0x00000080

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    def _get_mouse_pos() -> Tuple[int, int]:
        try:
            pt = POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return pt.x, pt.y
        except Exception:
            return 100, 100
else:
    def _get_mouse_pos() -> Tuple[int, int]:
        return 100, 100



class FloatingHUD:

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._root: Optional[tk.Tk] = None
        self._label: Optional[tk.Label] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._target_text = ""
        self._target_bg = "#1f2937"
        self._target_fg = "#ffffff"
        self._hide_timer: Optional[threading.Timer] = None
        self._running = False

        if self.enabled:
            self._start_loop()

    def _start_loop(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run_gui, daemon=True)
            self._thread.start()

    def _run_gui(self) -> None:
        try:
            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.configure(bg="#1f2937")

            # Apply Windows non-activating style
            if IS_WINDOWS:
                try:
                    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
                    if not hwnd:
                        hwnd = root.winfo_id()
                    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    style |= (WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TOOLWINDOW)
                    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
                except Exception:
                    pass

            label = tk.Label(
                root,
                text="",
                font=("Segoe UI", 10, "bold"),
                bg="#1f2937",
                fg="#ffffff",
                padx=14,
                pady=6,
            )
            label.pack()

            root.withdraw()
            self._root = root
            self._label = label

            def check_updates():
                with self._lock:
                    if self._target_text:
                        label.config(
                            text=self._target_text,
                            bg=self._target_bg,
                            fg=self._target_fg,
                        )
                        root.config(bg=self._target_bg)
                        mx, my = _get_mouse_pos()
                        root.geometry(f"+{mx + 15}+{my + 15}")
                        root.deiconify()
                        root.lift()
                        root.attributes("-topmost", True)
                        try:
                            root.update_idletasks()
                            root.update()
                        except Exception:
                            pass
                    else:
                        root.withdraw()
                if self._running:
                    root.after(50, check_updates)

            root.after(50, check_updates)
            root.mainloop()
        except Exception:
            pass

    def show_status(self, state: str, text_override: Optional[str] = None) -> None:
        if not self.enabled or not self._running:
            return

        status_styles: Dict[str, Tuple[str, str, str]] = {
            "LISTENING": ("🔴 Recording...", "#dc2626", "#ffffff"),
            "RECORDING": ("🔴 Recording...", "#dc2626", "#ffffff"),
            "TRANSCRIBING": ("⚡ Transcribing...", "#7c3aed", "#ffffff"),
            "STT": ("⚡ Transcribing...", "#7c3aed", "#ffffff"),
            "CLEANING": ("✨ Polishing...", "#2563eb", "#ffffff"),
            "PASTE": ("✅ Pasted", "#16a34a", "#ffffff"),
            "INBOX": ("📝 Saved to Inbox", "#16a34a", "#ffffff"),
            "JOURNAL": ("📓 Saved to Journal", "#16a34a", "#ffffff"),
            "MEETING": ("🎙️ Meeting Session", "#2563eb", "#ffffff"),
            "ERROR": ("⚠️ Error", "#b91c1c", "#ffffff"),
        }

        style = status_styles.get(state.upper())
        if not style:
            return

        disp_text = text_override or style[0]
        bg = style[1]
        fg = style[2]

        with self._lock:
            if self._hide_timer:
                self._hide_timer.cancel()
                self._hide_timer = None

            self._target_text = disp_text
            self._target_bg = bg
            self._target_fg = fg

        # Auto-hide after 1.2s for completion / paste events
        if state.upper() in {"PASTE", "INBOX", "JOURNAL", "ERROR"}:
            timer = threading.Timer(1.2, self._hide)
            timer.daemon = True
            with self._lock:
                self._hide_timer = timer
            timer.start()

    def _hide(self) -> None:
        with self._lock:
            self._target_text = ""
            self._hide_timer = None

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self._hide()

    def close(self) -> None:
        self.enabled = False
        self._running = False
        self._hide()
        if self._root:
            try:
                self._root.quit()
            except Exception:
                pass
