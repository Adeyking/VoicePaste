from types import SimpleNamespace
from voicepaste.cleanup import check_model_loaded_in_vram


def test_check_model_loaded_in_vram_returns_true_when_present() -> None:
    class DummyResponse:
        status_code = 200

        def json(self):
            return {
                "models": [
                    {"name": "qwen3.5:9b", "size": 6000000000},
                    {"name": "whisper:latest", "size": 1500000000},
                ]
            }

    result = check_model_loaded_in_vram(
        ollama_url="http://127.0.0.1:11434",
        active_model="qwen3.5:9b",
        get_fn=lambda *a, **k: DummyResponse(),
    )
    assert result is True


def test_check_model_loaded_in_vram_returns_false_when_missing() -> None:
    class DummyResponse:
        status_code = 200

        def json(self):
            return {"models": [{"name": "phi4:latest"}]}

    result = check_model_loaded_in_vram(
        ollama_url="http://127.0.0.1:11434",
        active_model="qwen3.5:9b",
        get_fn=lambda *a, **k: DummyResponse(),
    )
    assert result is False


def test_check_model_loaded_in_vram_returns_none_on_http_error() -> None:
    class DummyResponse:
        status_code = 500

    result = check_model_loaded_in_vram(
        ollama_url="http://127.0.0.1:11434",
        active_model="qwen3.5:9b",
        get_fn=lambda *a, **k: DummyResponse(),
    )
    assert result is None


def test_check_model_loaded_in_vram_returns_none_on_network_exception() -> None:
    def _raise_error(*args, **kwargs):
        raise ConnectionError("Ollama offline")

    result = check_model_loaded_in_vram(
        ollama_url="http://127.0.0.1:11434",
        active_model="qwen3.5:9b",
        get_fn=_raise_error,
    )
    assert result is None
