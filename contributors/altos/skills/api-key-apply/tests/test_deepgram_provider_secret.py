from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deepgram-provider-secret.py"
SPEC = importlib.util.spec_from_file_location("deepgram_provider_secret", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_matrix_tokens_filters_provider_and_state(tmp_path: Path) -> None:
    matrix = tmp_path / "api-matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "keys": [
                    {"provider": "deepgram", "key": "one", "status": "ok"},
                    {"provider": "deepgram", "key": "two", "status": "invalid"},
                    {"provider": "cerebras", "key": "three", "status": "ok"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert MODULE._matrix_tokens(matrix) == ["one"]


def test_silence_wav_is_valid() -> None:
    payload = MODULE._silence_wav()
    assert payload.startswith(b"RIFF")
    assert b"WAVE" in payload[:16]


def test_receipt_never_contains_value(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    MODULE._write_receipt(path, {"key_id": "nonsecret-id", "value_persisted_locally": False})
    text = path.read_text(encoding="utf-8")
    assert "keyString" not in text
    assert "\"key\"" not in text
