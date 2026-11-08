"""Regression tests for rescue-call state and identity safety."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.services.rescue_call_context_service import (
    RescueCallContextError,
    RescueCallContextService,
    RescueCallLookup,
)


def create_rescue_database(path: Path) -> None:
    """Create the minimum schema needed for call-context verification."""
    with sqlite3.connect(path) as db:
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
                status TEXT NOT NULL
            );

            CREATE TABLE rescue_calls (
                call_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                assignment_id TEXT NOT NULL,
                driver_id TEXT NOT NULL,
                status TEXT NOT NULL
            );
            """
        )

        db.execute(
            "INSERT INTO rescue_cases VALUES (?, ?)",
            ("case-001", "calling"),
        )
        db.execute(
            "INSERT INTO rescue_assignments VALUES (?, ?, ?, ?)",
            ("assignment-001", "case-001", "driver-suresh", "call_queued"),
        )
        db.execute(
            "INSERT INTO rescue_calls VALUES (?, ?, ?, ?, ?)",
            (
                "call-001",
                "case-001",
                "assignment-001",
                "driver-suresh",
                "in_progress",
            ),
        )


@pytest.fixture
def rescue_db(tmp_path: Path) -> Path:
    path = tmp_path / "rescue_security.db"
    create_rescue_database(path)
    return path


@pytest.fixture
def valid_lookup() -> RescueCallLookup:
    return RescueCallLookup(
        case_id="case-001",
        assignment_id="assignment-001",
        driver_id="driver-suresh",
        call_id="call-001",
    )


def verify(
    db_path: Path,
    lookup: RescueCallLookup,
    *,
    provider_verified: bool = True,
    driver_verified: bool = True,
):
    return RescueCallContextService(db_path).resolve(
        lookup,
        provider_event_verified=provider_verified,
        driver_identity_verified=driver_verified,
    )


def test_valid_connected_call_is_eligible(
    rescue_db: Path,
    valid_lookup: RescueCallLookup,
):
    result = verify(rescue_db, valid_lookup)

    assert result.case_id == valid_lookup.case_id
    assert result.assignment_id == valid_lookup.assignment_id
    assert result.driver_id == valid_lookup.driver_id
    assert result.call_id == valid_lookup.call_id
    assert result.identity_verified is True
    assert result.call_active is True


@pytest.mark.parametrize(
    "field,wrong_value",
    [
        ("case_id", "case-999"),
        ("assignment_id", "assignment-999"),
        ("driver_id", "driver-amit"),
        ("call_id", "call-999"),
    ],
)
def test_mismatched_identity_is_rejected(
    rescue_db: Path,
    valid_lookup: RescueCallLookup,
    field: str,
    wrong_value: str,
):
    values = {
        "case_id": valid_lookup.case_id,
        "assignment_id": valid_lookup.assignment_id,
        "driver_id": valid_lookup.driver_id,
        "call_id": valid_lookup.call_id,
    }
    values[field] = wrong_value

    with pytest.raises(RescueCallContextError):
        verify(rescue_db, RescueCallLookup(**values))


@pytest.mark.parametrize(
    "provider_verified,driver_verified",
    [
        (False, True),
        (True, False),
        (False, False),
    ],
)
def test_unverified_call_or_driver_is_rejected(
    rescue_db: Path,
    valid_lookup: RescueCallLookup,
    provider_verified: bool,
    driver_verified: bool,
):
    with pytest.raises(RescueCallContextError):
        verify(
            rescue_db,
            valid_lookup,
            provider_verified=provider_verified,
            driver_verified=driver_verified,
        )


@pytest.mark.parametrize(
    "status",
    ["queued", "completed", "failed", "cancelled"],
)
def test_non_connected_calls_are_rejected(
    rescue_db: Path,
    valid_lookup: RescueCallLookup,
    status: str,
):
    with sqlite3.connect(rescue_db) as db:
        db.execute(
            "UPDATE rescue_calls SET status = ? WHERE call_id = ?",
            (status, valid_lookup.call_id),
        )

    with pytest.raises(RescueCallContextError):
        verify(rescue_db, valid_lookup)


@pytest.mark.parametrize(
    "status",
    ["accepted", "declined", "completed", "cancelled"],
)
def test_assignment_not_waiting_for_response_is_rejected(
    rescue_db: Path,
    valid_lookup: RescueCallLookup,
    status: str,
):
    with sqlite3.connect(rescue_db) as db:
        db.execute(
            """
            UPDATE rescue_assignments
            SET status = ?
            WHERE assignment_id = ?
            """,
            (status, valid_lookup.assignment_id),
        )

    with pytest.raises(RescueCallContextError):
        verify(rescue_db, valid_lookup)


@pytest.mark.parametrize(
    "status",
    ["completed", "cancelled", "approved"],
)
def test_inactive_rescue_case_is_rejected(
    rescue_db: Path,
    valid_lookup: RescueCallLookup,
    status: str,
):
    with sqlite3.connect(rescue_db) as db:
        db.execute(
            "UPDATE rescue_cases SET status = ? WHERE case_id = ?",
            (status, valid_lookup.case_id),
        )

    with pytest.raises(RescueCallContextError):
        verify(rescue_db, valid_lookup)


def test_missing_database_fails_closed(
    tmp_path: Path,
    valid_lookup: RescueCallLookup,
):
    missing = tmp_path / "does_not_exist.db"

    with pytest.raises(RescueCallContextError):
        verify(missing, valid_lookup)

    assert not missing.exists()


def test_successful_validation_does_not_change_database(
    rescue_db: Path,
    valid_lookup: RescueCallLookup,
):
    with sqlite3.connect(rescue_db) as db:
        before = db.execute(
            """
            SELECT status
            FROM rescue_assignments
            WHERE assignment_id = ?
            """,
            (valid_lookup.assignment_id,),
        ).fetchone()

    verify(rescue_db, valid_lookup)

    with sqlite3.connect(rescue_db) as db:
        after = db.execute(
            """
            SELECT status
            FROM rescue_assignments
            WHERE assignment_id = ?
            """,
            (valid_lookup.assignment_id,),
        ).fetchone()

    assert before == after == ("call_queued",)
