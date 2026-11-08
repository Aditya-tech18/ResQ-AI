"""Regression tests for the durable telephony event inbox."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest

from app.services.telephony_event_inbox import (
    TelephonyEventInbox,
    TelephonyInboxError,
)
from app.services.telephony_webhook_security import (
    AuthenticatedTelephonyEvent,
)


@pytest.fixture
def clock(monkeypatch):
    current = [1_800_000_000]
    monkeypatch.setattr(
        TelephonyEventInbox,
        "_now",
        staticmethod(lambda: current[0]),
    )
    return current


@pytest.fixture
def inbox(tmp_path, clock):
    return TelephonyEventInbox(
        tmp_path / "inbox.sqlite3",
        lease_seconds=60,
    )


def event(event_id="evt-001", payload=None):
    return AuthenticatedTelephonyEvent(
        event_id=event_id,
        event_type="call.completed",
        provider_call_id="call-001",
        occurred_at=datetime.now(UTC),
        payload=payload
        if payload is not None
        else {
            "event_id": event_id,
            "driver_id": "DRV-002",
            "language": "te",
        },
    )


def test_submit(inbox):
    assert inbox.submit(event()) is True
    assert inbox.get_status("evt-001")["status"] == "pending"


def test_duplicate_is_idempotent(inbox):
    item = event()
    assert inbox.submit(item) is True
    assert inbox.submit(item) is False


def test_conflicting_duplicate_rejected(inbox):
    inbox.submit(event())

    with pytest.raises(TelephonyInboxError, match="Conflicting"):
        inbox.submit(event(payload={"changed": True}))


def test_claim(inbox):
    inbox.submit(event())
    job = inbox.claim_next()

    assert job.event_id == "evt-001"
    assert job.attempt_count == 1
    assert job.payload["driver_id"] == "DRV-002"
    assert inbox.get_status("evt-001")["status"] == "processing"


def test_empty_queue(inbox):
    assert inbox.claim_next() is None


def test_active_lease_blocks_second_worker(inbox):
    inbox.submit(event())
    assert inbox.claim_next() is not None
    assert inbox.claim_next() is None


def test_complete(inbox):
    inbox.submit(event())
    job = inbox.claim_next()
    inbox.complete(job.event_id, job.lease_token)

    assert inbox.get_status(job.event_id)["status"] == "completed"
    assert inbox.claim_next() is None


def test_wrong_token_cannot_complete(inbox):
    inbox.submit(event())
    job = inbox.claim_next()

    with pytest.raises(TelephonyInboxError):
        inbox.complete(job.event_id, "wrong-token")

    assert inbox.get_status(job.event_id)["status"] == "processing"


def test_expired_lease_recovery(inbox, clock):
    inbox.submit(event())
    first = inbox.claim_next()

    clock[0] += 61

    second = inbox.claim_next()

    assert second.event_id == first.event_id
    assert second.attempt_count == 2
    assert second.lease_token != first.lease_token


def test_old_worker_cannot_complete(inbox, clock):
    inbox.submit(event())
    old = inbox.claim_next()

    clock[0] += 61
    new = inbox.claim_next()

    with pytest.raises(TelephonyInboxError):
        inbox.complete(old.event_id, old.lease_token)

    inbox.complete(new.event_id, new.lease_token)

    assert inbox.get_status("evt-001")["status"] == "completed"


def test_retry(inbox, clock):
    inbox.submit(event())
    first = inbox.claim_next()

    inbox.retry(
        first.event_id,
        first.lease_token,
        error="Network timeout",
        delay_seconds=30,
    )

    assert inbox.claim_next() is None
    assert inbox.get_status("evt-001")["last_error"] == "Network timeout"

    clock[0] += 30
    second = inbox.claim_next()

    assert second.attempt_count == 2


def test_retry_then_complete(inbox, clock):
    inbox.submit(event())
    first = inbox.claim_next()

    inbox.retry(
        first.event_id,
        first.lease_token,
        error="Temporary failure",
        delay_seconds=10,
    )

    clock[0] += 10
    second = inbox.claim_next()
    inbox.complete(second.event_id, second.lease_token)

    status = inbox.get_status("evt-001")
    assert status["status"] == "completed"
    assert status["attempt_count"] == 2
    assert status["last_error"] is None


def test_restart_preserves_pending_event(tmp_path, clock):
    path = tmp_path / "persistent.db"

    first = TelephonyEventInbox(path)
    first.submit(event())

    restarted = TelephonyEventInbox(path)

    assert restarted.claim_next().event_id == "evt-001"


def test_restart_recovers_expired_lease(tmp_path, clock):
    path = tmp_path / "persistent.db"

    first = TelephonyEventInbox(path, lease_seconds=10)
    first.submit(event())
    first.claim_next()

    restarted = TelephonyEventInbox(path, lease_seconds=10)

    assert restarted.claim_next() is None

    clock[0] += 11

    assert restarted.claim_next().attempt_count == 2


def test_concurrent_claim_only_one_wins(tmp_path, clock):
    path = tmp_path / "concurrent.db"

    TelephonyEventInbox(path).submit(event())
    barrier = Barrier(5)

    def worker(_):
        local = TelephonyEventInbox(path)
        barrier.wait(timeout=10)
        job = local.claim_next()
        return job.event_id if job else None

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(worker, range(5)))

    assert results.count("evt-001") == 1
    assert results.count(None) == 4


def test_concurrent_submissions_are_idempotent(tmp_path, clock):
    path = tmp_path / "concurrent.db"
    TelephonyEventInbox(path)

    barrier = Barrier(5)

    def worker(_):
        local = TelephonyEventInbox(path)
        barrier.wait(timeout=10)
        return local.submit(event())

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(worker, range(5)))

    assert sum(results) == 1


def test_unicode_payload(inbox):
    inbox.submit(
        event(
            payload={
                "hindi": "मैं आ रहा हूँ",
                "telugu": "నేను వస్తాను",
            }
        )
    )

    job = inbox.claim_next()

    assert job.payload["hindi"] == "मैं आ रहा हूँ"
    assert job.payload["telugu"] == "నేను వస్తాను"


def test_unserializable_payload_rejected(inbox):
    with pytest.raises(TelephonyInboxError):
        inbox.submit(event(payload={"bad": object()}))


def test_invalid_event_object_rejected(inbox):
    with pytest.raises(TelephonyInboxError):
        inbox.submit({"event_id": "fake"})


@pytest.mark.parametrize("lease", [0, -1, 1.5, True, None])
def test_invalid_lease_rejected(tmp_path, lease):
    with pytest.raises(ValueError):
        TelephonyEventInbox(
            tmp_path / "inbox.db",
            lease_seconds=lease,
        )


@pytest.mark.parametrize("delay", [-1, 1.5, True, None])
def test_invalid_retry_delay(inbox, delay):
    inbox.submit(event())
    job = inbox.claim_next()

    with pytest.raises(ValueError):
        inbox.retry(
            job.event_id,
            job.lease_token,
            error="failure",
            delay_seconds=delay,
        )


def test_database_failure_fails_closed(inbox):
    with sqlite3.connect(inbox.db_path) as db:
        db.execute("DROP TABLE telephony_inbox")

    with pytest.raises(TelephonyInboxError):
        inbox.submit(event())


def test_missing_event_status(inbox):
    assert inbox.get_status("unknown") is None


def test_completed_event_not_requeued(inbox):
    item = event()
    inbox.submit(item)

    job = inbox.claim_next()
    inbox.complete(job.event_id, job.lease_token)

    assert inbox.submit(item) is False
    assert inbox.claim_next() is None


def test_missing_database_directory(tmp_path):
    path = tmp_path / "missing" / "inbox.db"

    with pytest.raises(TelephonyInboxError):
        TelephonyEventInbox(path)

    assert not path.exists()
