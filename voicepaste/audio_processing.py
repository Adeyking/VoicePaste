import math
import numpy as np


class StreamingBiquadHighpassFilter:
    """Stateful 2nd-order Butterworth high-pass filter (default cutoff 80Hz) that
    maintains filter state across sequential audio frames to remove desk rumble,
    proximity boom, and plosive thumps without boundary clicks/pops.
    """

    def __init__(self, sample_rate: int = 16000, cutoff_hz: float = 80.0):
        self.sample_rate = sample_rate
        self.cutoff_hz = cutoff_hz
        omega = 2.0 * math.pi * cutoff_hz / sample_rate
        sn = math.sin(omega)
        cs = math.cos(omega)
        alpha = sn / (2.0 * math.sqrt(2.0))

        b0 = (1.0 + cs) / 2.0
        b1 = -(1.0 + cs)
        b2 = (1.0 + cs) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cs
        a2 = 1.0 - alpha

        self.nb0 = b0 / a0
        self.nb1 = b1 / a0
        self.nb2 = b2 / a0
        self.na1 = a1 / a0
        self.na2 = a2 / a0

        self.x1 = 0.0
        self.x2 = 0.0
        self.y1 = 0.0
        self.y2 = 0.0

    def reset(self) -> None:
        """Reset internal delay registers."""
        self.x1 = 0.0
        self.x2 = 0.0
        self.y1 = 0.0
        self.y2 = 0.0

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Process an audio frame and update internal filter state."""
        if samples.size == 0:
            return samples

        orig_shape = samples.shape
        x = samples.astype(np.float32).reshape(-1)
        y = np.empty_like(x)

        nb0, nb1, nb2 = self.nb0, self.nb1, self.nb2
        na1, na2 = self.na1, self.na2
        x1, x2 = self.x1, self.x2
        y1, y2 = self.y1, self.y2

        for i in range(len(x)):
            xi = x[i]
            yi = nb0 * xi + nb1 * x1 + nb2 * x2 - na1 * y1 - na2 * y2
            y[i] = yi
            x2 = x1
            x1 = xi
            y2 = y1
            y1 = yi

        self.x1 = x1
        self.x2 = x2
        self.y1 = y1
        self.y2 = y2
        return y.reshape(orig_shape)


def biquad_highpass_filter(
    samples: np.ndarray,
    sample_rate: int = 16000,
    cutoff_hz: float = 80.0,
) -> np.ndarray:
    """Apply a 2nd-order Butterworth high-pass filter (cutoff 80Hz) to remove
    low-frequency proximity effect boom, desk rumble, and plosive air blast thumps.
    """
    if samples.size == 0:
        return samples
    flt = StreamingBiquadHighpassFilter(sample_rate=sample_rate, cutoff_hz=cutoff_hz)
    return flt.process(samples)


def normalize_audio(
    samples: np.ndarray,
    target_peak_fraction: float = 0.85,
    max_gain: float = 8.0,
) -> np.ndarray:
    """Safely normalizes audio amplitude to a clean target peak (default -1.5dB / 85% of full scale)
    to prevent digital clipping and provide consistent dynamic range to Whisper.
    """
    if samples.size == 0:
        return samples

    float_samples = samples.astype(np.float32)
    peak = float(np.max(np.abs(float_samples)))
    if peak <= 100.0:  # Near complete silence — do not amplify noise floor
        return samples.astype(np.int16)

    target_peak = 32767.0 * target_peak_fraction
    gain = min(max_gain, max(0.25, target_peak / peak))
    normalized = float_samples * gain
    return np.clip(normalized, -32768.0, 32767.0).astype(np.int16)


def trim_trailing_silence(
    samples: np.ndarray,
    sample_rate: int = 16000,
    silence_threshold_rms: float = 250.0,
    window_ms: int = 20,
    safety_pad_ms: int = 150,
) -> np.ndarray:
    """Trims trailing dead air captured between when the speaker stops talking
    and when the Push-to-Talk button is physically released.

    Uses a conservative RMS energy check with a safety lookback pad (default 150ms)
    so quiet trailing consonants (/s/, /t/, /p/) are never clipped.
    """
    if samples.size == 0 or len(samples) < int(sample_rate * 0.4):
        return samples

    window_size = int(sample_rate * (window_ms / 1000.0))
    safety_pad = int(sample_rate * (safety_pad_ms / 1000.0))
    flat = samples.reshape(-1)
    total_samples = len(flat)

    last_speech_idx = total_samples
    for i in range(total_samples - window_size, -1, -window_size):
        chunk = flat[i : i + window_size].astype(np.float32)
        rms = float(np.sqrt(np.mean(chunk**2)))
        if rms > silence_threshold_rms:
            last_speech_idx = min(total_samples, i + window_size + safety_pad)
            break

    if last_speech_idx < total_samples - int(sample_rate * 0.15):
        return flat[:last_speech_idx].reshape(-1)

    return samples


def preprocess_audio_for_stt(
    samples: np.ndarray,
    sample_rate: int = 16000,
    cutoff_hz: float = 80.0,
    target_peak_fraction: float = 0.85,
) -> np.ndarray:
    """Pipeline combining 80Hz low-cut filtering, trailing silence trimming, and peak normalization."""
    if samples.size == 0:
        return samples
    filtered = biquad_highpass_filter(samples, sample_rate=sample_rate, cutoff_hz=cutoff_hz)
    trimmed = trim_trailing_silence(filtered, sample_rate=sample_rate)
    return normalize_audio(trimmed, target_peak_fraction=target_peak_fraction)