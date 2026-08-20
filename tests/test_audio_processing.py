import numpy as np
import pytest
from voicepaste.audio_processing import (
    biquad_highpass_filter,
    normalize_audio,
    preprocess_audio_for_stt,
)


def test_empty_audio_handling():
    empty = np.array([], dtype=np.int16)
    assert biquad_highpass_filter(empty).size == 0
    assert normalize_audio(empty).size == 0
    assert preprocess_audio_for_stt(empty).size == 0


def test_highpass_filter_attenuates_low_frequency():
    # 16kHz sampling, 1 second
    sr = 16000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    
    # 40Hz sub-bass tone (should be heavily attenuated by 80Hz filter)
    low_freq = (np.sin(2 * np.pi * 40 * t) * 10000).astype(np.int16)
    filtered_low = biquad_highpass_filter(low_freq, sample_rate=sr, cutoff_hz=80.0)
    
    # 1000Hz speech tone (should pass through with minimal attenuation)
    speech_freq = (np.sin(2 * np.pi * 1000 * t) * 10000).astype(np.int16)
    filtered_speech = biquad_highpass_filter(speech_freq, sample_rate=sr, cutoff_hz=80.0)
    
    low_energy = np.mean(filtered_low[1000:] ** 2)
    speech_energy = np.mean(filtered_speech[1000:] ** 2)
    
    # Low frequency energy must be significantly attenuated compared to speech frequency
    assert low_energy < (speech_energy * 0.25)


def test_normalize_audio_peak_scaling():
    sr = 16000
    t = np.linspace(0, 0.5, sr // 2, endpoint=False)
    # Quiet signal with peak at ~5000
    quiet = (np.sin(2 * np.pi * 500 * t) * 5000).astype(np.int16)
    
    normalized = normalize_audio(quiet, target_peak_fraction=0.85)
    
    # Peak should now be close to 0.85 * 32767 = 27851
    peak = np.max(np.abs(normalized))
    assert 24000 <= peak <= 28500


def test_normalize_audio_preserves_silence():
    # Complete silence should not be amplified into noise
    silence = np.zeros(1000, dtype=np.int16)
    norm = normalize_audio(silence)
    assert np.max(np.abs(norm)) == 0


def test_preprocess_audio_for_stt_full_pipeline():
    raw = np.random.randint(-10000, 10000, size=(16000, 1), dtype=np.int16)
    processed = preprocess_audio_for_stt(raw)
    assert processed.shape == raw.shape
    assert processed.dtype == np.int16
    assert np.max(np.abs(processed)) > 0