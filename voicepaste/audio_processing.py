import math
import numpy as np


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

    nb0 = b0 / a0
    nb1 = b1 / a0
    nb2 = b2 / a0
    na1 = a1 / a0
    na2 = a2 / a0

    orig_shape = samples.shape
    x = samples.astype(np.float32).reshape(-1)
    y = np.empty_like(x)

    x1, x2 = 0.0, 0.0
    y1, y2 = 0.0, 0.0
    for i in range(len(x)):
        xi = x[i]
        yi = nb0 * xi + nb1 * x1 + nb2 * x2 - na1 * y1 - na2 * y2
        y[i] = yi
        x2 = x1
        x1 = xi
        y2 = y1
        y1 = yi

    return y.reshape(orig_shape)


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


def preprocess_audio_for_stt(
    samples: np.ndarray,
    sample_rate: int = 16000,
    cutoff_hz: float = 80.0,
    target_peak_fraction: float = 0.85,
) -> np.ndarray:
    """Pipeline combining 80Hz low-cut filtering and peak normalization."""
    if samples.size == 0:
        return samples
    filtered = biquad_highpass_filter(samples, sample_rate=sample_rate, cutoff_hz=cutoff_hz)
    return normalize_audio(filtered, target_peak_fraction=target_peak_fraction)