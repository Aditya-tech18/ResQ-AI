"""Tests for audio validation and upload security."""

import io
import os
import wave

os.environ["DISPATCH_DEV_API"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.audio_processing import (  # noqa: E402
    AudioValidationError,
    validate_audio,
)


def make_wav() -> bytes:
    output = io.BytesIO()

    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 160)

    return output.getvalue()


def test_valid_wav():
    result = validate_audio(make_wav(), "audio/wav")
    assert result.size_bytes > 0
    assert result.content_type == "audio/wav"
    assert len(result.sha256) == 64


def test_empty_audio_rejected():
    with pytest.raises(AudioValidationError):
        validate_audio(b"", "audio/wav")


def test_invalid_audio_rejected():
    with pytest.raises(AudioValidationError):
        validate_audio(b"fake audio", "audio/wav")


def test_unsupported_format_rejected():
    with pytest.raises(AudioValidationError):
        validate_audio(b"hello", "application/pdf")


def test_audio_upload_requires_jwt():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/audio/upload",
            files={
                "file": (
                    "test.wav",
                    make_wav(),
                    "audio/wav",
                )
            },
        )

    assert response.status_code == 401


def test_invalid_jwt_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/audio/upload",
            headers={"Authorization": "Bearer invalid.jwt.token"},
            files={
                "file": (
                    "test.wav",
                    make_wav(),
                    "audio/wav",
                )
            },
        )

    assert response.status_code == 401


def test_audio_route_in_openapi():
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/audio/upload" in response.json()["paths"]
