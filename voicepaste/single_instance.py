from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional, TextIO


def _pid_is_alive(pid: int) -> bool:
    """Return True iff a process with this PID exists AND is a Python/VoicePaste instance."""
    if pid <= 0 or pid == os.getpid():
        return False
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                if exit_code.value != STILL_ACTIVE:
                    return False

                # Check process image name to avoid PID recycling collisions
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(len(buf))
                if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    img = buf.value.lower()
                    if any(k in img for k in ("python", "voicepaste", "localdictate")):
                        return True
                    return False
                return True
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class SingleInstanceGuard:
    """Cross-process lock to prevent multiple VoicePaste listeners.

    On Windows, abnormal termination (taskkill /F, crash, power loss) can leave
    the lock file on disk with a PID that no longer exists. Before giving up we
    check whether the recorded PID is still alive; if it isn't, we delete the
    stale lock file and try once more so the next launch can recover
    automatically.
    """

    def __init__(self, lock_name: str = "voicepaste-global") -> None:
        self._lock_path = Path(tempfile.gettempdir()) / f"{lock_name}.lock"
        self._handle: TextIO | None = None
        self._last_stale_pid: Optional[int] = None

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    @property
    def last_stale_pid(self) -> Optional[int]:
        """PID that was cleaned up, if the previous acquire() took over a stale lock."""
        return self._last_stale_pid

    def _read_recorded_pid(self) -> Optional[int]:
        try:
            raw = self._lock_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _try_lock(self, handle: TextIO) -> bool:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def acquire(self) -> None:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_stale_pid = None

        for attempt in range(2):
            handle = self._lock_path.open("a+", encoding="utf-8")
            if self._try_lock(handle):
                try:
                    handle.seek(0)
                    handle.truncate(0)
                    handle.write(str(os.getpid()))
                    handle.flush()
                except OSError:
                    pass
                self._handle = handle
                return

            # Lock is held by someone. See if the recorded PID is still alive.
            recorded_pid = self._read_recorded_pid()
            handle.close()

            if attempt == 0 and (recorded_pid is None or not _pid_is_alive(recorded_pid)):
                # Stale or corrupted lock from a previous crash/force-kill. Remove and retry.
                self._last_stale_pid = recorded_pid
                try:
                    self._lock_path.unlink()
                except OSError:
                    pass
                continue

            raise RuntimeError(
                "VoicePaste is already running in another process "
                f"(pid={recorded_pid})."
            )

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        if handle.closed:
            self._handle = None
            return
        try:
            if os.name == "nt":
                import msvcrt

                try:
                    handle.seek(0)
                except (PermissionError, OSError):
                    return
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except (PermissionError, OSError):
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except (PermissionError, OSError):
                    pass
        finally:
            try:
                handle.close()
            except (PermissionError, OSError):
                pass
            try:
                self._lock_path.unlink()
            except (PermissionError, OSError):
                pass
            self._handle = None
