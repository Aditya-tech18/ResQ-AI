"""Authenticated voice triage tests using controlled dependencies."""

import os
from unittest.mock import Mock
from uuid import uuid4

os.environ["DISPATCH_DEV_API"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.dependencies import AuthContext, get_auth_context  # noqa: E402
from app.api.shipments import get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def environment():
    merchant_id = str(uuid4())
    shipment_id = uuid4()

    database = Mock()
    database.scalar.return_value = Mock(
        id=str(shipment_id),
        merchant_id=merchant_id,
    )

    def fake_auth():
        return AuthContext(
            user_id=str(uuid4()),
            merchant_id=merchant_id,
            role="dispatcher",
        )

    def fake_db():
        yield database

    app.dependency_overrides[get_auth_context] = fake_auth
    app.dependency_overrides[get_db] = fake_db

    try:
        with TestClient(app) as client:
            yield client, database, merchant_id, shipment_id
    finally:
        app.dependency_overrides.pop(get_auth_context, None)
        app.dependency_overrides.pop(get_db, None)


def test_authenticated_triage_success(environment):
    client, database, _, shipment_id = environment

    response = client.post(
        "/api/v1/voice/triage",
        json={
            "shipment_id": str(shipment_id),
            "transcript": "Customer ghar pe nahi tha",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["reason"] == "customer_unavailable"
    assert response.json()["suggested_action"] == "reschedule_pickup"

    database.scalar.assert_called_once()


def test_missing_shipment_returns_404(environment):
    client, database, _, shipment_id = environment
    database.scalar.return_value = None

    response = client.post(
        "/api/v1/voice/triage",
        json={
            "shipment_id": str(shipment_id),
            "transcript": "Address galat hai",
        },
    )

    assert response.status_code == 404


def test_unknown_reason_requires_review(environment):
    client, _, _, shipment_id = environment

    response = client.post(
        "/api/v1/voice/triage",
        json={
            "shipment_id": str(shipment_id),
            "transcript": "Hello team please check",
        },
    )

    assert response.status_code == 200
    assert response.json()["reason"] == "unknown"
    assert response.json()["requires_human_review"] is True


def test_invalid_payload_rejected(environment):
    client, _, _, _ = environment

    response = client.post(
        "/api/v1/voice/triage",
        json={
            "shipment_id": "invalid-uuid",
            "transcript": "",
        },
    )

    assert response.status_code == 422
