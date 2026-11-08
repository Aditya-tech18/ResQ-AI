"""Voice intelligence tests."""

import os

os.environ["DISPATCH_DEV_API"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.voice_intelligence import (  # noqa: E402
    VoiceReason,
    analyze_transcript,
)


@pytest.mark.parametrize(
    ("transcript", "expected"),
    [
        (
            "Customer ghar pe nahi tha, kal pickup karunga",
            VoiceReason.CUSTOMER_UNAVAILABLE,
        ),
        (
            "Address galat hai",
            VoiceReason.ADDRESS_ISSUE,
        ),
        (
            "Gate band hai",
            VoiceReason.GATE_CLOSED,
        ),
        (
            "Parcel ready nahi hai",
            VoiceReason.PACKAGE_NOT_READY,
        ),
        (
            "Traffic jam mein pickup late ho gaya",
            VoiceReason.PICKUP_DELAY,
        ),
        (
            "Customer not available",
            VoiceReason.CUSTOMER_UNAVAILABLE,
        ),
        (
            "पता गलत है",
            VoiceReason.ADDRESS_ISSUE,
        ),
    ],
)
def test_classification(transcript, expected):
    result = analyze_transcript(transcript)
    assert result.reason == expected


def test_unknown_reason_requires_review():
    result = analyze_transcript("Hello dispatch team")

    assert result.reason == VoiceReason.UNKNOWN
    assert result.requires_human_review is True


def test_ambiguous_transcript_requires_review():
    result = analyze_transcript("Customer not available and address galat")

    assert result.requires_human_review is True


def test_empty_transcript_rejected():
    with pytest.raises(ValueError):
        analyze_transcript("   ")


def test_voice_endpoint_requires_auth():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/voice/analyze",
            json={"transcript": "Address galat hai"},
        )

    assert response.status_code == 401


def test_voice_endpoint_rejects_invalid_jwt():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/voice/analyze",
            json={"transcript": "Gate band hai"},
            headers={"Authorization": "Bearer invalid.jwt.token"},
        )

    assert response.status_code == 401


def test_voice_endpoint_documented():
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/voice/analyze" in response.json()["paths"]
