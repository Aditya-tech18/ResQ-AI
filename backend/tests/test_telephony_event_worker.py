"""Tests for safe telephony lifecycle event processing."""

from datetime import UTC, datetime

import pytest

from app.services.telephony_event_inbox import TelephonyEventInbox
from app.services.telephony_event_worker import TelephonyEventWorker
from app.services.telephony_webhook_security import (
    AuthenticatedTelephonyEvent,
)


@pytest.fixture
def inbox(tmp_path):
    return TelephonyEventInbox(tmp_path / "worker.db")


def make_event(event_id="evt-1", event_type="call.completed"):
    provider_call_id = "provider-001"
    return AuthenticatedTelephonyEvent(
        event_id=event_id,
        event_type=event_type,
        provider_call_id=provider_call_id,
        occurred_at=datetime.now(UTC),
        payload={
            "event_id": event_id,
            "event_type": event_type,
            "provider_call_id": provider_call_id,
        },
    )


def test_idle_worker(inbox):
    worker = TelephonyEventWorker(inbox)
    assert worker.process_one().outcome == "idle"


def test_successful_processing(inbox):
    inbox.submit(make_event())
    handled = []

    worker = TelephonyEventWorker(
        inbox,
        handlers={
            "call.completed": lambda job: handled.append(job.event_id),
        },
    )

    result = worker.process_one()

    assert result.outcome == "completed"
    assert handled == ["evt-1"]
    assert inbox.get_status("evt-1")["status"] == "completed"


def test_failed_handler_is_retryable(inbox):
    inbox.submit(make_event())

    def fail(_job):
        raise RuntimeError("Temporary failure")

    worker = TelephonyEventWorker(
        inbox,
        handlers={"call.completed": fail},
    )

    result = worker.process_one()

    assert result.outcome == "retry_scheduled"
    assert inbox.get_status("evt-1")["status"] == "pending"


def test_missing_handler_blocked(inbox):
    inbox.submit(make_event())

    worker = TelephonyEventWorker(inbox)

    assert worker.process_one().outcome == "blocked"


@pytest.mark.parametrize(
    "event_type",
    [
        "driver.accepted",
        "driver.declined",
        "driver.consent",
        "driver.confirmed",
    ],
)
def test_driver_consent_not_automatically_processed(
    inbox,
    event_type,
):
    inbox.submit(make_event(event_type=event_type))

    worker = TelephonyEventWorker(inbox)

    result = worker.process_one()

    assert result.outcome == "blocked"
    assert inbox.get_status("evt-1")["status"] == "pending"


def test_unknown_event_blocked(inbox):
    inbox.submit(make_event(event_type="unknown.event"))

    worker = TelephonyEventWorker(inbox)

    assert worker.process_one().outcome == "blocked"


def test_payload_mismatch_blocked(inbox):
    original = make_event()

    altered = AuthenticatedTelephonyEvent(
        event_id=original.event_id,
        event_type=original.event_type,
        provider_call_id=original.provider_call_id,
        occurred_at=original.occurred_at,
        payload={
            "event_id": original.event_id,
            "event_type": original.event_type,
            "provider_call_id": "wrong-provider",
        },
    )

    inbox.submit(altered)

    worker = TelephonyEventWorker(
        inbox,
        handlers={"call.completed": lambda job: None},
    )

    assert worker.process_one().outcome == "blocked"


def test_batch_processing(inbox):
    for index in range(5):
        inbox.submit(make_event(event_id=f"evt-{index}"))

    worker = TelephonyEventWorker(
        inbox,
        handlers={"call.completed": lambda job: None},
    )

    first = worker.process_batch(limit=3)
    second = worker.process_batch(limit=3)

    assert first["processed"] == 3
    assert second["processed"] == 2


def test_consent_handler_cannot_be_registered(inbox):
    with pytest.raises(ValueError):
        TelephonyEventWorker(
            inbox,
            handlers={
                "driver.accepted": lambda job: None,
            },
        )


def test_unknown_handler_cannot_be_registered(inbox):
    with pytest.raises(ValueError):
        TelephonyEventWorker(
            inbox,
            handlers={
                "unknown.event": lambda job: None,
            },
        )


def test_non_callable_handler_rejected(inbox):
    with pytest.raises(TypeError):
        TelephonyEventWorker(
            inbox,
            handlers={"call.completed": "invalid"},
        )


@pytest.mark.parametrize("limit", [0, -1, 1001, True, 1.5])
def test_invalid_batch_limit(inbox, limit):
    worker = TelephonyEventWorker(inbox)

    with pytest.raises(ValueError):
        worker.process_batch(limit=limit)


@pytest.mark.parametrize("delay", [-1, True, 1.5])
def test_invalid_retry_delay(inbox, delay):
    with pytest.raises(ValueError):
        TelephonyEventWorker(
            inbox,
            retry_delay_seconds=delay,
        )


def test_invalid_inbox_rejected():
    with pytest.raises(TypeError):
        TelephonyEventWorker(None)
