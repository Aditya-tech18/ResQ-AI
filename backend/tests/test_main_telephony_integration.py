"""Verify the webhook endpoint is reachable from the real main app."""

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient


def test_main_app_webhook_accepts_signed_event(
    tmp_path,
    monkeypatch,
):
    from app.main import app
    from app.services.telephony_event_inbox import TelephonyEventInbox
    from app.services.telephony_webhook_ingestion import (
        TelephonyWebhookIngestionService,
    )

    secret = "resq-test-webhook-secret-2026-minimum-32-bytes"
    inbox = TelephonyEventInbox(tmp_path / "telephony.sqlite3")

    service = TelephonyWebhookIngestionService(
        secret=secret,
        inbox=inbox,
    )

    monkeypatch.setattr(
        app.state,
        "telephony_ingestion_service",
        service,
        raising=False,
    )

    timestamp = str(int(time.time()))

    event = {
        "event_id": "main-app-integration-001",
        "event_type": "call.completed",
        "provider_call_id": "provider-test-call-001",
        "occurred_at": datetime.now(UTC).isoformat(),
    }

    body = json.dumps(event).encode()

    signature = hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/telephony/webhooks",
            content=body,
            headers={
                "X-ResQ-Timestamp": timestamp,
                "X-ResQ-Signature": signature,
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 202, response.text
    assert response.json()["accepted"] is True


def test_main_app_webhook_rejects_unsigned_request(
    tmp_path,
    monkeypatch,
):
    from app.main import app
    from app.services.telephony_event_inbox import TelephonyEventInbox
    from app.services.telephony_webhook_ingestion import (
        TelephonyWebhookIngestionService,
    )

    service = TelephonyWebhookIngestionService(
        secret="resq-test-unsigned-secret-2026-minimum-32-bytes",
        inbox=TelephonyEventInbox(tmp_path / "telephony.sqlite3"),
    )

    monkeypatch.setattr(
        app.state,
        "telephony_ingestion_service",
        service,
        raising=False,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/telephony/webhooks",
            json={"event_id": "unsigned"},
        )

    assert response.status_code == 401
