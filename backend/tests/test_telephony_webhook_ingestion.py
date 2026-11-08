"""Tests for authenticated webhook ingestion and durability."""

import hashlib
import hmac
import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app.services.telephony_event_inbox import TelephonyEventInbox
from app.services.telephony_webhook_ingestion import (
    TelephonyWebhookIngestionService,
    WebhookIngestionError,
)

SECRET = b"resq-ai-webhook-integration-test-secret-123456"
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


@pytest.fixture
def inbox(tmp_path):
    return TelephonyEventInbox(tmp_path / "webhooks.db")


@pytest.fixture
def service(inbox):
    return TelephonyWebhookIngestionService(
        secret=SECRET,
        inbox=inbox,
    )


def payload(
    event_id="evt-001",
    event_type="call.completed",
    provider_call_id="provider-001",
    occurred_at=None,
):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "provider_call_id": provider_call_id,
        "occurred_at": (occurred_at or NOW.isoformat()),
    }


def encode(data):
    return json.dumps(
        data,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sign(body, timestamp=None, secret=SECRET):
    timestamp = timestamp or str(int(NOW.timestamp()))

    return hmac.new(
        secret,
        timestamp.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()


def ingest(service, data=None, *, timestamp=None, signature=None):
    body = encode(payload() if data is None else data)
    timestamp = timestamp or str(int(NOW.timestamp()))

    return service.ingest(
        body=body,
        timestamp=timestamp,
        signature=signature or sign(body, timestamp),
        now=NOW,
    )


def test_valid_event_is_stored(service, inbox):
    result = ingest(service)

    assert result.accepted is True
    assert result.outcome == "stored"
    assert result.event_id == "evt-001"
    assert inbox.get_status("evt-001")["status"] == "pending"


def test_identical_duplicate_acknowledged(service, inbox):
    first = ingest(service)
    second = ingest(service)

    assert first.outcome == "stored"
    assert second.outcome == "duplicate"

    with sqlite3.connect(inbox.db_path) as db:
        count = db.execute("SELECT COUNT(*) FROM telephony_inbox").fetchone()[0]

    assert count == 1


def test_conflicting_duplicate_rejected(service):
    ingest(service)

    with pytest.raises(WebhookIngestionError):
        ingest(service, payload(provider_call_id="different-call"))


def test_tampered_body_rejected(service, inbox):
    original = encode(payload())
    signature = sign(original)

    modified = encode(payload(event_id="evt-tampered"))

    with pytest.raises(WebhookIngestionError):
        service.ingest(
            body=modified,
            timestamp=str(int(NOW.timestamp())),
            signature=signature,
            now=NOW,
        )

    assert inbox.get_status("evt-tampered") is None


def test_wrong_secret_rejected(service):
    body = encode(payload())

    with pytest.raises(WebhookIngestionError):
        service.ingest(
            body=body,
            timestamp=str(int(NOW.timestamp())),
            signature=sign(
                body,
                secret=b"wrong-secret-123456789012345678901234",
            ),
            now=NOW,
        )


@pytest.mark.parametrize(
    "bad_timestamp",
    ["", "-1", "1.5", "not-a-time", "１２３", " 123"],
)
def test_invalid_timestamp_rejected(service, bad_timestamp):
    body = encode(payload())

    with pytest.raises(WebhookIngestionError):
        service.ingest(
            body=body,
            timestamp=bad_timestamp,
            signature="0" * 64,
            now=NOW,
        )


@pytest.mark.parametrize("offset", [-301, 301, -3600, 3600])
def test_expired_or_future_request_rejected(service, offset):
    body = encode(payload())
    timestamp = str(int(NOW.timestamp()) + offset)

    with pytest.raises(WebhookIngestionError):
        service.ingest(
            body=body,
            timestamp=timestamp,
            signature=sign(body, timestamp),
            now=NOW,
        )


@pytest.mark.parametrize("offset", [-300, 300])
def test_boundary_request_allowed(service, offset):
    body = encode(payload())
    timestamp = str(int(NOW.timestamp()) + offset)

    result = service.ingest(
        body=body,
        timestamp=timestamp,
        signature=sign(body, timestamp),
        now=NOW,
    )

    assert result.outcome == "stored"


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_id", ""),
        ("event_id", "contains spaces"),
        ("event_type", ""),
        ("event_type", "UPPERCASE"),
        ("provider_call_id", ""),
        ("provider_call_id", 123),
    ],
)
def test_invalid_identifiers_rejected(service, field, value):
    data = payload()
    data[field] = value

    with pytest.raises(WebhookIngestionError):
        ingest(service, data)


@pytest.mark.parametrize(
    "missing",
    [
        "event_id",
        "event_type",
        "provider_call_id",
        "occurred_at",
    ],
)
def test_missing_fields_rejected(service, missing):
    data = payload()
    del data[missing]

    with pytest.raises(WebhookIngestionError):
        ingest(service, data)


def test_event_occurrence_outside_window_rejected(service):
    old = NOW - timedelta(minutes=10)

    with pytest.raises(WebhookIngestionError):
        ingest(service, payload(occurred_at=old.isoformat()))


def test_timezone_naive_occurrence_rejected(service):
    with pytest.raises(WebhookIngestionError):
        ingest(service, payload(occurred_at="2026-11-06T12:00:00"))


def test_invalid_json_rejected(service):
    body = b"{broken-json"
    timestamp = str(int(NOW.timestamp()))

    with pytest.raises(WebhookIngestionError):
        service.ingest(
            body=body,
            timestamp=timestamp,
            signature=sign(body, timestamp),
            now=NOW,
        )


def test_json_array_rejected(service):
    with pytest.raises(WebhookIngestionError):
        ingest(service, [])


def test_non_finite_number_rejected(service):
    data = payload()
    data["metadata"] = {"distance": float("nan")}

    with pytest.raises(WebhookIngestionError):
        ingest(service, data)


def test_unicode_payload_preserved(service, inbox):
    data = payload()
    data["driver_message"] = "मैं आ रहा हूँ"
    data["telugu"] = "నేను వస్తాను"

    ingest(service, data)

    job = inbox.claim_next()

    assert job.payload["driver_message"] == "मैं आ रहा हूँ"
    assert job.payload["telugu"] == "నేను వస్తాను"


def test_event_survives_service_restart(tmp_path):
    path = tmp_path / "persistent.db"

    first = TelephonyWebhookIngestionService(
        secret=SECRET,
        inbox=TelephonyEventInbox(path),
    )

    assert ingest(first).outcome == "stored"

    restarted = TelephonyWebhookIngestionService(
        secret=SECRET,
        inbox=TelephonyEventInbox(path),
    )

    assert ingest(restarted).outcome == "duplicate"


def test_database_failure_is_not_acknowledged(service, inbox):
    with sqlite3.connect(inbox.db_path) as db:
        db.execute("DROP TABLE telephony_inbox")

    with pytest.raises(WebhookIngestionError):
        ingest(service)


def test_driver_consent_event_is_only_queued(service, inbox):
    result = ingest(
        service,
        payload(event_type="driver.accepted"),
    )

    assert result.outcome == "stored"
    assert inbox.get_status("evt-001")["status"] == "pending"

    # Ingestion must never directly approve a rescue assignment.


def test_invalid_secret_rejected(inbox):
    with pytest.raises(ValueError):
        TelephonyWebhookIngestionService(
            secret="short",
            inbox=inbox,
        )


def test_invalid_inbox_rejected():
    with pytest.raises(TypeError):
        TelephonyWebhookIngestionService(
            secret=SECRET,
            inbox=None,
        )


def test_oversized_body_rejected(service):
    body = b"x" * 300_000
    timestamp = str(int(NOW.timestamp()))

    with pytest.raises(WebhookIngestionError):
        service.ingest(
            body=body,
            timestamp=timestamp,
            signature=sign(body, timestamp),
            now=NOW,
        )


def test_invalid_signature_format_rejected(service):
    body = encode(payload())

    with pytest.raises(WebhookIngestionError):
        service.ingest(
            body=body,
            timestamp=str(int(NOW.timestamp())),
            signature="not-a-signature",
            now=NOW,
        )
