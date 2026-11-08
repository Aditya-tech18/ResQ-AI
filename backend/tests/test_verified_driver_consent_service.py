"""Security and transaction tests for verified rescue driver consent."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from app.services.verified_driver_consent_service import (
    DriverConsentError,
    VerifiedDriverConsentService,
    VerifiedDriverResponse,
)

CASE_ID = "case-001"
ASSIGNMENT_ID = "assignment-001"
DRIVER_ID = "driver-suresh"
CALL_ID = "call-001"
PROVIDER_CALL_ID = "provider-call-001"


@pytest.fixture
def database(tmp_path: Path) -> Path:
    """Create a real-schema SQLite database with one active call."""
    path = tmp_path / "verified_consent.db"

    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys = ON")

        db.executescript(
            """
            CREATE TABLE rescue_cases (
                case_id TEXT PRIMARY KEY,
                status TEXT NOT NULL
            );

            CREATE TABLE rescue_assignments (
                assignment_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                replacement_driver_id TEXT NOT NULL,
                status TEXT NOT NULL,
                accepted_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE rescue_calls (
                call_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                assignment_id TEXT NOT NULL,
                driver_id TEXT NOT NULL,
                status TEXT NOT NULL,
                provider_call_id TEXT,
                ended_at TEXT
            );

            CREATE TABLE rescue_events (
                event_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

        db.execute(
            "INSERT INTO rescue_cases VALUES (?, ?)",
            (CASE_ID, "calling"),
        )

        db.execute(
            """
            INSERT INTO rescue_assignments
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                ASSIGNMENT_ID,
                CASE_ID,
                DRIVER_ID,
                "call_queued",
                None,
                None,
            ),
        )

        db.execute(
            """
            INSERT INTO rescue_calls
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                CALL_ID,
                CASE_ID,
                ASSIGNMENT_ID,
                DRIVER_ID,
                "in_progress",
                PROVIDER_CALL_ID,
                None,
            ),
        )

    return path


@pytest.fixture
def valid_response() -> VerifiedDriverResponse:
    return VerifiedDriverResponse(
        case_id=CASE_ID,
        assignment_id=ASSIGNMENT_ID,
        driver_id=DRIVER_ID,
        call_id=CALL_ID,
        provider_call_id=PROVIDER_CALL_ID,
        accepted=True,
        explicit_confirmation=True,
        provider_event_verified=True,
        driver_identity_verified=True,
    )


def record(
    database: Path,
    response: VerifiedDriverResponse,
):
    return VerifiedDriverConsentService(database).record(response)


def get_state(database: Path) -> dict:
    with sqlite3.connect(database) as db:
        assignment = db.execute(
            """
            SELECT status, accepted_at
            FROM rescue_assignments
            WHERE assignment_id = ?
            """,
            (ASSIGNMENT_ID,),
        ).fetchone()

        call = db.execute(
            """
            SELECT status, ended_at
            FROM rescue_calls
            WHERE call_id = ?
            """,
            (CALL_ID,),
        ).fetchone()

        events = db.execute(
            """
            SELECT event_type, payload_json
            FROM rescue_events
            ORDER BY created_at
            """
        ).fetchall()

    return {
        "assignment": assignment,
        "call": call,
        "events": events,
    }


def assert_unchanged(database: Path) -> None:
    state = get_state(database)

    assert state["assignment"] == ("call_queued", None)
    assert state["call"] == ("in_progress", None)
    assert state["events"] == []


def update(
    database: Path,
    table: str,
    field: str,
    value: str,
) -> None:
    """Update only approved fixture columns using fixed SQL statements."""
    queries = {
        ("rescue_cases", "status"): "UPDATE rescue_cases SET status = ?",
        ("rescue_assignments", "status"): "UPDATE rescue_assignments SET status = ?",
        (
            "rescue_assignments",
            "replacement_driver_id",
        ): "UPDATE rescue_assignments SET replacement_driver_id = ?",
        ("rescue_calls", "status"): "UPDATE rescue_calls SET status = ?",
        ("rescue_calls", "provider_call_id"): "UPDATE rescue_calls SET provider_call_id = ?",
    }

    try:
        query = queries[(table, field)]
    except KeyError as exc:
        raise ValueError("Unexpected test update") from exc

    with sqlite3.connect(database) as db:
        db.execute(query, (value,))


def test_acceptance_updates_assignment_and_call(
    database: Path,
    valid_response: VerifiedDriverResponse,
):
    result = record(database, valid_response)
    state = get_state(database)

    assert result.accepted is True
    assert result.assignment_status == "accepted"
    assert result.call_status == "completed"
    assert result.recorded_at

    assert state["assignment"][0] == "accepted"
    assert state["assignment"][1] is not None
    assert state["call"][0] == "completed"
    assert state["call"][1] is not None


def test_decline_records_without_acceptance_timestamp(
    database: Path,
    valid_response: VerifiedDriverResponse,
):
    result = record(
        database,
        replace(valid_response, accepted=False),
    )
    state = get_state(database)

    assert result.accepted is False
    assert result.assignment_status == "declined"
    assert state["assignment"] == ("declined", None)
    assert state["call"][0] == "completed"


def test_success_writes_single_audit_event(
    database: Path,
    valid_response: VerifiedDriverResponse,
):
    record(database, valid_response)

    events = get_state(database)["events"]

    assert len(events) == 1
    assert events[0][0] == "verified_driver_response"

    payload = json.loads(events[0][1])

    assert payload["assignment_id"] == ASSIGNMENT_ID
    assert payload["driver_id"] == DRIVER_ID
    assert payload["call_id"] == CALL_ID
    assert payload["accepted"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("case_id", "wrong-case"),
        ("assignment_id", "wrong-assignment"),
        ("driver_id", "driver-amit"),
        ("call_id", "wrong-call"),
        ("provider_call_id", "wrong-provider-call"),
    ],
)
def test_identity_mismatch_rejected_without_mutation(
    database: Path,
    valid_response: VerifiedDriverResponse,
    field: str,
    value: str,
):
    with pytest.raises(DriverConsentError):
        record(
            database,
            replace(valid_response, **{field: value}),
        )

    assert_unchanged(database)


@pytest.mark.parametrize(
    "field",
    [
        "provider_event_verified",
        "driver_identity_verified",
        "explicit_confirmation",
    ],
)
def test_missing_verification_rejected(
    database: Path,
    valid_response: VerifiedDriverResponse,
    field: str,
):
    with pytest.raises(DriverConsentError):
        record(
            database,
            replace(valid_response, **{field: False}),
        )

    assert_unchanged(database)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "yes",
        1,
        0,
    ],
)
def test_acceptance_must_be_boolean(
    database: Path,
    valid_response: VerifiedDriverResponse,
    value: object,
):
    with pytest.raises(DriverConsentError):
        record(
            database,
            replace(valid_response, accepted=value),
        )

    assert_unchanged(database)


@pytest.mark.parametrize(
    "status",
    ["queued", "completed", "failed", "cancelled"],
)
def test_inactive_call_rejected(
    database: Path,
    valid_response: VerifiedDriverResponse,
    status: str,
):
    update(database, "rescue_calls", "status", status)

    before = get_state(database)

    with pytest.raises(DriverConsentError):
        record(database, valid_response)

    assert get_state(database) == before


@pytest.mark.parametrize(
    "status",
    ["accepted", "declined", "completed"],
)
def test_non_pending_assignment_rejected(
    database: Path,
    valid_response: VerifiedDriverResponse,
    status: str,
):
    update(database, "rescue_assignments", "status", status)

    before = get_state(database)

    with pytest.raises(DriverConsentError):
        record(database, valid_response)

    assert get_state(database) == before


@pytest.mark.parametrize(
    "status",
    ["completed", "cancelled"],
)
def test_closed_rescue_case_rejected(
    database: Path,
    valid_response: VerifiedDriverResponse,
    status: str,
):
    update(database, "rescue_cases", "status", status)

    before = get_state(database)

    with pytest.raises(DriverConsentError):
        record(database, valid_response)

    assert get_state(database) == before


def test_duplicate_response_is_rejected(
    database: Path,
    valid_response: VerifiedDriverResponse,
):
    record(database, valid_response)

    first_state = get_state(database)

    with pytest.raises(DriverConsentError):
        record(database, valid_response)

    assert get_state(database) == first_state


def test_conflicting_response_cannot_reverse_acceptance(
    database: Path,
    valid_response: VerifiedDriverResponse,
):
    record(database, valid_response)

    with pytest.raises(DriverConsentError):
        record(
            database,
            replace(valid_response, accepted=False),
        )

    assert get_state(database)["assignment"][0] == "accepted"


def test_concurrent_responses_only_one_commits(
    database: Path,
    valid_response: VerifiedDriverResponse,
):
    responses = [
        valid_response,
        replace(valid_response, accepted=False),
    ]

    def attempt(response: VerifiedDriverResponse):
        try:
            return record(database, response)
        except DriverConsentError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, responses))

    successes = [item for item in results if item is not None]

    assert len(successes) == 1
    assert len(get_state(database)["events"]) == 1
    assert get_state(database)["call"][0] == "completed"


def test_missing_database_does_not_get_created(
    tmp_path: Path,
    valid_response: VerifiedDriverResponse,
):
    missing = tmp_path / "missing.db"

    with pytest.raises(DriverConsentError):
        record(missing, valid_response)

    assert not missing.exists()


def test_database_error_rolls_back_transaction(
    database: Path,
    valid_response: VerifiedDriverResponse,
):
    with sqlite3.connect(database) as db:
        db.execute("DROP TABLE rescue_events")

    with pytest.raises(DriverConsentError):
        record(database, valid_response)

    with sqlite3.connect(database) as db:
        assignment = db.execute("SELECT status FROM rescue_assignments").fetchone()

        call = db.execute("SELECT status FROM rescue_calls").fetchone()

    assert assignment == ("call_queued",)
    assert call == ("in_progress",)


def test_database_driver_mismatch_rejected(
    database: Path,
    valid_response: VerifiedDriverResponse,
):
    update(
        database,
        "rescue_assignments",
        "replacement_driver_id",
        "driver-amit",
    )

    before = get_state(database)

    with pytest.raises(DriverConsentError):
        record(database, valid_response)

    assert get_state(database) == before
