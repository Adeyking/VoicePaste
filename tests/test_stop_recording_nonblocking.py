import time
import threading
from unittest.mock import MagicMock
import numpy as np
import pytest

from voicepaste.engine import PushToTalkClient, VoicePasteConfig, build_parser


def test_stop_recording_non_blocking_performance():
    args = build_parser().parse_args([])
    cfg = VoicePasteConfig.load(args)
    client = PushToTalkClient(cfg)

    # Set up recording state with dummy frames (500ms > 300ms minimum)
    client._recording = True
    client._stream = MagicMock()
    client._frames = [np.zeros((8000, 1), dtype=np.int16)]

    client._record_start_monotonic = time.perf_counter()
    client._current_recording_id = 1

    # Simulate an active background partial thread that is sleeping
    def slow_worker():
        while not client._partial_stop_event.wait(0.5):
            pass

    t = threading.Thread(target=slow_worker, daemon=True)
    t.start()
    client._partial_thread = t

    # Measure stop_recording duration
    t0 = time.perf_counter()
    # Mock _process_utterance so we don't start actual STT during test
    client._process_utterance = MagicMock()
    client.stop_recording()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    # Must complete almost instantaneously (< 30ms) without blocking on background worker
    assert elapsed_ms < 30.0
    assert client._recording is False
    assert client._partial_stop_event.is_set()
    assert client._process_utterance.called
