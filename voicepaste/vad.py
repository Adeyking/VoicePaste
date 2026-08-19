from __future__ import annotations

import time
from typing import Callable, List
import numpy as np


def detect_silence_window(
    audio_data: np.ndarray,
    sample_rate: int = 16000,
    hold_window_s: float = 0.35,
    energy_threshold: float = 400.0,
) -> bool:
    """Return True if RMS energy of the trailing audio window is below energy_threshold (silence)."""
    if audio_data is None or audio_data.size == 0:
        return True
    window_samples = int(hold_window_s * sample_rate)
    flat_audio = audio_data.ravel()
    tail = flat_audio[-window_samples:] if flat_audio.size >= window_samples else flat_audio
    if tail.size == 0:
        return True
    try:
        rms = float(np.sqrt(np.mean(tail.astype(np.float32) ** 2)))
        return rms < energy_threshold
    except (ValueError, TypeError, MemoryError):
        return True


def wait_for_silence(
    get_audio_frames: Callable[[], List[np.ndarray]],
    is_active: Callable[[], bool],
    sample_rate: int = 16000,
    hold_window_s: float = 0.35,
    max_hold_s: float = 1.0,
    energy_threshold: float = 400.0,
    poll_interval_s: float = 0.08,
    time_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bool:
    """Hold until trailing audio RMS energy drops below energy_threshold or max_hold_s expires.

    Returns True if silence was detected within max_hold_s; False if max_hold_s timed out.
    """
    deadline = time_fn() + max_hold_s
    while time_fn() < deadline:
        if not is_active():
            return True
        frames = get_audio_frames()
        if not frames:
            return True
        try:
            audio_tail = np.concatenate(frames, axis=0)
        except Exception:
            return True

        if detect_silence_window(
            audio_tail,
            sample_rate=sample_rate,
            hold_window_s=hold_window_s,
            energy_threshold=energy_threshold,
        ):
            return True

        sleep_fn(poll_interval_s)

    return False
