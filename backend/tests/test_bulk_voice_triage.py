"""Bulk voice triage tests."""

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
    database = Mock()
    database.scalar.return_value = Mock()

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
            yield client, database
    finally:
        app.dependency_overrides.pop(get_auth_context, None)
        app.dependency_overrides.pop(get_db, None)


def make_item(transcript):
    return {
        "shipment_id": str(uuid4()),
        "transcript": transcript,
    }


def test_bulk_classification(environment):
    client, _ = environment

    response = client.post(
        "/api/v1/voice/bulk-triage",
        json={
            "items": [
                make_item("Address galat hai"),
                make_item("Gate band hai"),
                make_item("Customer ghar pe nahi tha"),
            ]
        },
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["total"] == 3
    assert data["analyzed"] == 3
    assert data["reason_counts"]["address_issue"] == 1
    assert data["reason_counts"]["gate_closed"] == 1
    assert data["reason_counts"]["customer_unavailable"] == 1


def test_missing_shipment_not_exposed(environment):
    client, database = environment
    database.scalar.return_value = None

    response = client.post(
        "/api/v1/voice/bulk-triage",
        json={"items": [make_item("Address galat hai")]},
    )

    assert response.status_code == 200
    assert response.json()["not_found"] == 1
    assert response.json()["results"][0]["analysis"] is None


def test_bulk_limit(environment):
    client, _ = environment

    response = client.post(
        "/api/v1/voice/bulk-triage",
        json={"items": [make_item("Address galat hai") for _ in range(51)]},
    )

    assert response.status_code == 422


def test_bulk_requires_auth():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/voice/bulk-triage",
            json={"items": [make_item("Gate band hai")]},
        )

    assert response.status_code == 401


def test_bulk_route_registered():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    assert "/api/v1/voice/bulk-triage" in schema["paths"]
