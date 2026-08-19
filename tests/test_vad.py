import numpy as np
from voicepaste.vad import detect_silence_window, wait_for_silence


def test_detect_silence_window_returns_true_for_quiet_audio() -> None:
    # Generate 16kHz quiet audio (RMS ~50)
    quiet_audio = np.random.randint(-100, 100, size=16000, dtype=np.int16)
    assert detect_silence_window(quiet_audio, energy_threshold=400.0) is True


def test_detect_silence_window_returns_false_for_speech_audio() -> None:
    # Generate 16kHz loud audio (RMS ~3000)
    loud_audio = np.random.randint(-5000, 5000, size=16000, dtype=np.int16)
    assert detect_silence_window(loud_audio, energy_threshold=400.0) is False


def test_wait_for_silence_returns_immediately_on_silence() -> None:
    quiet_frame = np.random.randint(-100, 100, size=5600, dtype=np.int16)

    result = wait_for_silence(
        get_audio_frames=lambda: [quiet_frame],
        is_active=lambda: True,
        max_hold_s=1.0,
        energy_threshold=400.0,
    )
    assert result is True


def test_wait_for_silence_waits_and_detects_pause() -> None:
    loud_frame = np.random.randint(-5000, 5000, size=5600, dtype=np.int16)
    quiet_frame = np.random.randint(-50, 50, size=5600, dtype=np.int16)
    state = {"call_count": 0}

    def mock_get_frames():
        state["call_count"] += 1
        if state["call_count"] < 3:
            return [loud_frame]
        return [quiet_frame]

    result = wait_for_silence(
        get_audio_frames=mock_get_frames,
        is_active=lambda: True,
        max_hold_s=1.0,
        energy_threshold=400.0,
        sleep_fn=lambda _: None,
    )
    assert result is True
    assert state["call_count"] == 3


def test_wait_for_silence_times_out_on_continuous_speech() -> None:
    loud_frame = np.random.randint(-5000, 5000, size=5600, dtype=np.int16)
    time_state = {"clock": 0.0}

    def mock_time():
        time_state["clock"] += 0.2
        return time_state["clock"]

    result = wait_for_silence(
        get_audio_frames=lambda: [loud_frame],
        is_active=lambda: True,
        max_hold_s=0.5,
        energy_threshold=400.0,
        time_fn=mock_time,
        sleep_fn=lambda _: None,
    )
    assert result is False
