"""Voice triage API security tests."""

import os
from uuid import uuid4

os.environ["DISPATCH_DEV_API"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def payload():
    return {
        "shipment_id": str(uuid4()),
        "transcript": "Customer ghar pe nahi tha",
    }


def test_triage_requires_auth():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/voice/triage",
            json=payload(),
        )

    assert response.status_code == 401


def test_triage_rejects_invalid_token():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/voice/triage",
            json=payload(),
            headers={"Authorization": "Bearer invalid.jwt.token"},
        )

    assert response.status_code == 401


def test_triage_route_registered():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    assert "/api/v1/voice/triage" in schema["paths"]
