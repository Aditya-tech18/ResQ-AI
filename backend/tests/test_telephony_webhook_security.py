"""Security, replay, validation and concurrency tests for telephony webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from app.services.telephony_webhook_security import (
    SQLiteWebhookReplayStore,
    TelephonyWebhookError,
    TelephonyWebhookVerifier,
)

SECRET = b"resq-ai-test-secret-not-for-production-123456789"
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
TIMESTAMP = str(int(NOW.timestamp()))


@pytest.fixture
def store(tmp_path: Path) -> SQLiteWebhookReplayStore:
    return SQLiteWebhookReplayStore(tmp_path / "replay.sqlite3")


@pytest.fixture
def verifier(store: SQLiteWebhookReplayStore) -> TelephonyWebhookVerifier:
    return TelephonyWebhookVerifier(
        secret=SECRET,
        replay_store=store,
    )


def make_payload(
    *,
    event_id: str = "event-001",
    event_type: str = "call.completed",
    provider_call_id: str = "provider-call-001",
    occurred_at: str | None = None,
) -> dict:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "provider_call_id": provider_call_id,
        "occurred_at": occurred_at or NOW.isoformat(),
    }


def encode(payload: object) -> bytes:
    return json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sign(
    body: bytes,
    *,
    timestamp: str = TIMESTAMP,
    secret: bytes = SECRET,
) -> str:
    message = timestamp.encode("ascii") + b"." + body
    return hmac.new(
        secret,
        message,
        hashlib.sha256,
    ).hexdigest()


def authenticate(
    verifier: TelephonyWebhookVerifier,
    *,
    payload: object | None = None,
    body: bytes | None = None,
    timestamp: str = TIMESTAMP,
    signature: str | None = None,
    now: datetime = NOW,
):
    if body is None:
        body = encode(make_payload() if payload is None else payload)

    return verifier.verify(
        body=body,
        timestamp=timestamp,
        signature=signature
        if signature is not None
        else sign(
            body,
            timestamp=timestamp,
        ),
        now=now,
    )


def test_valid_authenticated_event(verifier):
    result = authenticate(verifier)

    assert result.event_id == "event-001"
    assert result.event_type == "call.completed"
    assert result.provider_call_id == "provider-call-001"
    assert result.occurred_at == NOW
    assert result.payload["event_id"] == "event-001"


def test_valid_signature_uppercase(verifier):
    body = encode(make_payload())

    result = authenticate(
        verifier,
        body=body,
        signature=sign(body).upper(),
    )

    assert result.event_id == "event-001"


def test_payload_tampering_rejected(verifier):
    original = encode(make_payload())
    tampered = encode(make_payload(provider_call_id="attacker-call"))

    with pytest.raises(TelephonyWebhookError):
        authenticate(
            verifier,
            body=tampered,
            signature=sign(original),
        )


def test_wrong_signing_secret_rejected(verifier):
    body = encode(make_payload())

    with pytest.raises(TelephonyWebhookError):
        authenticate(
            verifier,
            body=body,
            signature=sign(
                body,
                secret=b"completely-different-secret-123456789",
            ),
        )


@pytest.mark.parametrize(
    "signature",
    [
        "",
        "not-a-signature",
        "a" * 63,
        "a" * 65,
        "z" * 64,
        None,
        123,
    ],
)
def test_invalid_signature_rejected(verifier, signature):
    body = encode(make_payload())

    with pytest.raises(TelephonyWebhookError):
        verifier.verify(
            body=body,
            timestamp=TIMESTAMP,
            signature=signature,
            now=NOW,
        )


@pytest.mark.parametrize(
    "timestamp",
    [
        "",
        "-1",
        "1.5",
        "not-a-time",
        "1" * 13,
        " 123",
        "１２３",
    ],
)
def test_invalid_timestamp_rejected(verifier, timestamp):
    body = encode(make_payload())

    with pytest.raises(TelephonyWebhookError):
        verifier.verify(
            body=body,
            timestamp=timestamp,
            signature="0" * 64,
            now=NOW,
        )


@pytest.mark.parametrize("offset", [-301, 301, -3600, 3600])
def test_expired_or_future_request_rejected(verifier, offset):
    timestamp = str(int(NOW.timestamp()) + offset)

    with pytest.raises(TelephonyWebhookError):
        authenticate(
            verifier,
            timestamp=timestamp,
        )


@pytest.mark.parametrize("offset", [-300, 300])
def test_request_at_age_boundary_accepted(verifier, offset):
    timestamp = str(int(NOW.timestamp()) + offset)

    result = authenticate(
        verifier,
        timestamp=timestamp,
    )

    assert result.event_id == "event-001"


def test_replay_same_event_rejected(verifier):
    authenticate(verifier)

    with pytest.raises(
        TelephonyWebhookError,
        match="Duplicate",
    ):
        authenticate(verifier)


def test_same_event_id_with_new_signature_rejected(verifier):
    authenticate(verifier)

    changed = make_payload(event_type="call.started")

    with pytest.raises(
        TelephonyWebhookError,
        match="Duplicate",
    ):
        authenticate(verifier, payload=changed)


def test_distinct_event_ids_allowed(verifier):
    first = authenticate(
        verifier,
        payload=make_payload(event_id="event-A"),
    )
    second = authenticate(
        verifier,
        payload=make_payload(event_id="event-B"),
    )

    assert first.event_id != second.event_id


def test_replay_persists_across_verifier_instances(tmp_path):
    path = tmp_path / "shared-replay.db"

    first = TelephonyWebhookVerifier(
        secret=SECRET,
        replay_store=SQLiteWebhookReplayStore(path),
    )
    second = TelephonyWebhookVerifier(
        secret=SECRET,
        replay_store=SQLiteWebhookReplayStore(path),
    )

    authenticate(first)

    with pytest.raises(TelephonyWebhookError, match="Duplicate"):
        authenticate(second)


def test_concurrent_replay_only_one_succeeds(tmp_path):
    path = tmp_path / "concurrent-replay.db"
    barrier = Barrier(6)

    def attempt(_index: int) -> bool:
        local_verifier = TelephonyWebhookVerifier(
            secret=SECRET,
            replay_store=SQLiteWebhookReplayStore(path),
        )
        barrier.wait(timeout=10)

        try:
            authenticate(local_verifier)
            return True
        except TelephonyWebhookError:
            return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))

    assert sum(results) == 1

    with sqlite3.connect(path) as db:
        count = db.execute("SELECT COUNT(*) FROM telephony_webhook_events").fetchone()[0]

    assert count == 1


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{",
        b"not json",
        b"\xff",
        b"[]",
        b"null",
        b'"hello"',
        b"123",
    ],
)
def test_invalid_json_or_non_object_rejected(verifier, body):
    with pytest.raises(TelephonyWebhookError):
        authenticate(verifier, body=body)


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_id", ""),
        ("event_id", "contains spaces"),
        ("event_id", "x" * 129),
        ("event_id", 123),
        ("event_type", ""),
        ("event_type", 123),
        ("event_type", "x" * 101),
        ("provider_call_id", ""),
        ("provider_call_id", 123),
        ("provider_call_id", "x" * 257),
        ("occurred_at", ""),
        ("occurred_at", 123),
        ("occurred_at", "not-a-date"),
        ("occurred_at", "2026-11-06T12:00:00"),
    ],
)
def test_invalid_event_fields_rejected(
    verifier,
    field,
    value,
):
    payload = make_payload()
    payload[field] = value

    with pytest.raises(TelephonyWebhookError):
        authenticate(verifier, payload=payload)


@pytest.mark.parametrize(
    "field",
    [
        "event_id",
        "event_type",
        "provider_call_id",
        "occurred_at",
    ],
)
def test_missing_required_field_rejected(verifier, field):
    payload = make_payload()
    del payload[field]

    with pytest.raises(TelephonyWebhookError):
        authenticate(verifier, payload=payload)


@pytest.mark.parametrize("offset", [-301, 301])
def test_event_occurrence_outside_window_rejected(
    verifier,
    offset,
):
    occurred_at = (NOW + timedelta(seconds=offset)).isoformat()

    with pytest.raises(TelephonyWebhookError):
        authenticate(
            verifier,
            payload=make_payload(occurred_at=occurred_at),
        )


def test_timezone_aware_offset_normalized_to_utc(verifier):
    result = authenticate(
        verifier,
        payload=make_payload(
            occurred_at="2026-11-06T17:30:00+05:30",
        ),
    )

    assert result.occurred_at == NOW


def test_oversized_body_rejected(verifier):
    body = b"x" * (256 * 1024 + 1)

    with pytest.raises(
        TelephonyWebhookError,
        match="size",
    ):
        authenticate(verifier, body=body)


def test_non_bytes_body_rejected(verifier):
    with pytest.raises(TelephonyWebhookError):
        verifier.verify(
            body="not bytes",
            timestamp=TIMESTAMP,
            signature="a" * 64,
            now=NOW,
        )


def test_naive_current_time_rejected(verifier):
    with pytest.raises(TelephonyWebhookError):
        authenticate(
            verifier,
            now=datetime(2026, 11, 6, 12, 0),
        )


@pytest.mark.parametrize(
    "secret",
    [
        "short",
        b"short",
        "",
        123,
        None,
    ],
)
def test_invalid_secret_rejected(store, secret):
    with pytest.raises(TelephonyWebhookError):
        TelephonyWebhookVerifier(
            secret=secret,
            replay_store=store,
        )


@pytest.mark.parametrize(
    "age",
    [
        0,
        -1,
        3601,
        1.5,
        True,
    ],
)
def test_invalid_age_window_rejected(store, age):
    with pytest.raises(TelephonyWebhookError):
        TelephonyWebhookVerifier(
            secret=SECRET,
            replay_store=store,
            max_age_seconds=age,
        )


@pytest.mark.parametrize(
    "size",
    [
        0,
        100,
        1024 * 1024 + 1,
        1.5,
        True,
    ],
)
def test_invalid_body_limit_rejected(store, size):
    with pytest.raises(TelephonyWebhookError):
        TelephonyWebhookVerifier(
            secret=SECRET,
            replay_store=store,
            max_body_bytes=size,
        )


def test_missing_replay_directory_rejected(tmp_path):
    missing = tmp_path / "missing" / "replay.db"

    with pytest.raises(TelephonyWebhookError):
        SQLiteWebhookReplayStore(missing)

    assert not missing.exists()


def test_replay_store_claim_is_idempotent(store):
    assert store.claim("event-001", int(NOW.timestamp()))
    assert not store.claim("event-001", int(NOW.timestamp()))


def test_replay_store_pruning(store):
    now = int(NOW.timestamp())

    assert store.claim("old-event", now - 1000)
    assert store.claim("new-event", now)

    deleted = store.prune(now - 500)

    assert deleted == 1
    assert store.claim("old-event", now)
    assert not store.claim("new-event", now)


def test_replay_database_error_fails_closed(tmp_path):
    path = tmp_path / "replay.db"
    store = SQLiteWebhookReplayStore(path)

    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE telephony_webhook_events")

    verifier = TelephonyWebhookVerifier(
        secret=SECRET,
        replay_store=store,
    )

    with pytest.raises(TelephonyWebhookError):
        authenticate(verifier)


def test_invalid_signature_does_not_claim_event(store):
    verifier = TelephonyWebhookVerifier(
        secret=SECRET,
        replay_store=store,
    )

    body = encode(make_payload())

    with pytest.raises(TelephonyWebhookError):
        authenticate(
            verifier,
            body=body,
            signature="0" * 64,
        )

    result = authenticate(verifier, body=body)

    assert result.event_id == "event-001"


def test_invalid_payload_does_not_claim_event(store):
    verifier = TelephonyWebhookVerifier(
        secret=SECRET,
        replay_store=store,
    )

    invalid = make_payload(event_type="")

    with pytest.raises(TelephonyWebhookError):
        authenticate(verifier, payload=invalid)

    result = authenticate(verifier)

    assert result.event_id == "event-001"
