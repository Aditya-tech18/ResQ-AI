"""End-to-end HTTP tests for the telephony webhook gateway."""

import hashlib
import hmac
import json
import sqlite3
import time
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.telephony_webhooks import router
from app.telephony_webhook_app import create_telephony_webhook_app

SECRET = b"resq-ai-test-webhook-secret-12345678901234567890"
ENDPOINT = "/api/v1/telephony/webhooks"


@pytest.fixture
def gateway(tmp_path):
    database = tmp_path / "webhooks.sqlite3"

    app = create_telephony_webhook_app(
        secret=SECRET,
        database_path=database,
    )

    return TestClient(app), app, database


def make_payload(
    event_id="evt-api-001",
    event_type="call.completed",
):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "provider_call_id": "provider-call-001",
        "occurred_at": datetime.now(UTC).isoformat(),
    }


def signed_request(
    client,
    payload=None,
    *,
    secret=SECRET,
    timestamp=None,
):
    data = payload if payload is not None else make_payload()

    body = json.dumps(
        data,
        separators=(",", ":"),
    ).encode("utf-8")

    timestamp = str(int(time.time())) if timestamp is None else timestamp

    signature = hmac.new(
        secret,
        timestamp.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()

    return client.post(
        ENDPOINT,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-ResQ-Timestamp": timestamp,
            "X-ResQ-Signature": signature,
        },
    )


def test_health_endpoint(gateway):
    client, _, _ = gateway

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_valid_webhook_returns_202(gateway):
    client, app, _ = gateway

    response = signed_request(client)

    assert response.status_code == 202
    assert response.json() == {
        "accepted": True,
        "event_id": "evt-api-001",
        "status": "stored",
    }

    assert app.state.telephony_inbox.get_status("evt-api-001")["status"] == "pending"


def test_duplicate_webhook_acknowledged(gateway):
    client, _, database = gateway
    payload = make_payload()

    first = signed_request(client, payload)
    second = signed_request(client, payload)

    assert first.status_code == 202
    assert first.json()["status"] == "stored"

    assert second.status_code == 202
    assert second.json()["status"] == "duplicate"

    with sqlite3.connect(database) as db:
        count = db.execute("SELECT COUNT(*) FROM telephony_inbox").fetchone()[0]

    assert count == 1


def test_missing_authentication_headers(gateway):
    client, _, _ = gateway

    response = client.post(
        ENDPOINT,
        json=make_payload(),
    )

    assert response.status_code == 401


def test_invalid_signature_rejected(gateway):
    client, _, _ = gateway

    response = signed_request(
        client,
        secret=b"wrong-signing-secret-12345678901234567890",
    )

    assert response.status_code == 401
    assert "secret" not in response.text.lower()


def test_expired_request_rejected(gateway):
    client, _, _ = gateway

    response = signed_request(
        client,
        timestamp=str(int(time.time()) - 1000),
    )

    assert response.status_code == 401


def test_conflicting_duplicate_rejected(gateway):
    client, _, _ = gateway

    first = make_payload()
    second = dict(first)
    second["provider_call_id"] = "different-provider-call"

    assert signed_request(client, first).status_code == 202

    response = signed_request(client, second)

    assert response.status_code == 503


def test_consent_event_only_enqueued(gateway):
    client, app, _ = gateway

    response = signed_request(
        client,
        make_payload(
            event_id="evt-consent",
            event_type="driver.accepted",
        ),
    )

    assert response.status_code == 202

    assert app.state.telephony_inbox.get_status("evt-consent")["status"] == "pending"


def test_service_not_configured():
    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)

    response = client.post(
        ENDPOINT,
        json=make_payload(),
        headers={
            "X-ResQ-Timestamp": str(int(time.time())),
            "X-ResQ-Signature": "0" * 64,
        },
    )

    assert response.status_code == 503


def test_database_failure_returns_503(gateway):
    client, _, database = gateway

    with sqlite3.connect(database) as db:
        db.execute("DROP TABLE telephony_inbox")

    response = signed_request(client)

    assert response.status_code == 503


def test_multiple_events_persist(gateway):
    client, _, database = gateway

    for index in range(5):
        response = signed_request(
            client,
            make_payload(event_id=f"evt-{index}"),
        )

        assert response.status_code == 202

    with sqlite3.connect(database) as db:
        count = db.execute("SELECT COUNT(*) FROM telephony_inbox").fetchone()[0]

    assert count == 5
