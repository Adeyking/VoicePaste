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


def test_streaming_biquad_filter_chunk_continuity():
    from voicepaste.audio_processing import StreamingBiquadHighpassFilter
    # 1 second of random signal
    sr = 16000
    signal = np.random.randint(-10000, 10000, size=sr, dtype=np.int16)

    # 1) Full batch filter
    batch_filtered = biquad_highpass_filter(signal, sample_rate=sr, cutoff_hz=80.0)

    # 2) Streamed in 512-sample chunks
    stream_flt = StreamingBiquadHighpassFilter(sample_rate=sr, cutoff_hz=80.0)
    stream_chunks = []
    chunk_size = 512
    for i in range(0, len(signal), chunk_size):
        chunk = signal[i : i + chunk_size]
        stream_chunks.append(stream_flt.process(chunk))
    stream_filtered = np.concatenate(stream_chunks)

    # Streaming chunks must exactly equal the batch result with zero boundary discontinuity
    np.testing.assert_allclose(stream_filtered, batch_filtered, rtol=1e-5, atol=1e-4)

    # 3) Test reset
    stream_flt.reset()
    assert stream_flt.x1 == 0.0 and stream_flt.y1 == 0.0


def test_trim_trailing_silence():
    from voicepaste.audio_processing import trim_trailing_silence
    sr = 16000
    # 1.0s speech (amplitude 5000) followed by 0.6s silence (amplitude 0)
    t_speech = np.linspace(0, 1.0, sr, endpoint=False)
    speech = (np.sin(2 * np.pi * 400 * t_speech) * 5000).astype(np.int16)
    silence = np.zeros(int(sr * 0.6), dtype=np.int16)
    audio = np.concatenate([speech, silence])

    trimmed = trim_trailing_silence(audio, sample_rate=sr, silence_threshold_rms=250.0, safety_pad_ms=150)
    
    # Original length = 1.6s (25,600 samples)
    # Trimmed should be around 1.0s + 0.15s safety pad = 1.15s (18,400 samples)
    assert len(trimmed) < len(audio)
    assert len(trimmed) >= int(sr * 1.0)
    assert len(trimmed) <= int(sr * 1.25)