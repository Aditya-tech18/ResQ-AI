"""Atomic recording of authenticated rescue driver responses.

Important:
    The caller must authenticate the telephony event and driver identity
    before invoking this service. The flags supplied here are assertions
    from that trusted integration, not independently verified credentials.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


class DriverConsentError(ValueError):
    """Driver response could not be securely recorded."""


@dataclass(frozen=True, slots=True)
class VerifiedDriverResponse:
    case_id: str
    assignment_id: str
    driver_id: str
    call_id: str
    provider_call_id: str
    accepted: bool
    explicit_confirmation: bool
    provider_event_verified: bool
    driver_identity_verified: bool


@dataclass(frozen=True, slots=True)
class DriverConsentResult:
    case_id: str
    assignment_id: str
    driver_id: str
    accepted: bool
    assignment_status: str
    call_status: str
    recorded_at: str


class VerifiedDriverConsentService:
    """Persist a verified driver response in one SQLite transaction."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    @staticmethod
    def _validate_id(value: object, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DriverConsentError(f"Invalid {name}")
        return value.strip()

    def record(
        self,
        response: VerifiedDriverResponse,
    ) -> DriverConsentResult:
        if not isinstance(response, VerifiedDriverResponse):
            raise DriverConsentError("Invalid response object")

        if response.provider_event_verified is not True:
            raise DriverConsentError("Telephony provider event is not authenticated")

        if response.driver_identity_verified is not True:
            raise DriverConsentError("Driver identity is not verified")

        if type(response.accepted) is not bool:
            raise DriverConsentError("Driver response must be a boolean")

        if response.explicit_confirmation is not True:
            raise DriverConsentError("Explicit driver confirmation is required")

        case_id = self._validate_id(response.case_id, "case_id")
        assignment_id = self._validate_id(response.assignment_id, "assignment_id")
        driver_id = self._validate_id(response.driver_id, "driver_id")
        call_id = self._validate_id(response.call_id, "call_id")
        provider_call_id = self._validate_id(response.provider_call_id, "provider_call_id")

        if not self.db_path.is_file():
            raise DriverConsentError("Rescue database is unavailable")

        connection = None

        try:
            connection = sqlite3.connect(
                f"file:{self.db_path.resolve()}?mode=rw",
                uri=True,
                timeout=15,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 15000")
            connection.execute("BEGIN IMMEDIATE")

            row = connection.execute(
                """
                SELECT
                    c.call_id,
                    c.status AS call_status,
                    c.provider_call_id,
                    a.status AS assignment_status,
                    r.status AS case_status
                FROM rescue_calls AS c
                JOIN rescue_assignments AS a
                    ON a.assignment_id = c.assignment_id
                   AND a.case_id = c.case_id
                JOIN rescue_cases AS r
                    ON r.case_id = c.case_id
                WHERE c.call_id = ?
                  AND c.case_id = ?
                  AND c.assignment_id = ?
                  AND c.driver_id = ?
                  AND a.replacement_driver_id = ?
                LIMIT 1
                """,
                (
                    call_id,
                    case_id,
                    assignment_id,
                    driver_id,
                    driver_id,
                ),
            ).fetchone()

            if row is None:
                raise DriverConsentError("Call, case, assignment, or driver mismatch")

            if row["provider_call_id"] != provider_call_id:
                raise DriverConsentError("Provider call identifier mismatch")

            if row["call_status"] != "in_progress":
                raise DriverConsentError("Call is not actively connected")

            if row["assignment_status"] != "call_queued":
                raise DriverConsentError("Assignment is not awaiting a response")

            if row["case_status"] != "calling":
                raise DriverConsentError("Rescue case is not accepting responses")

            now = datetime.now(UTC).isoformat()
            assignment_status = "accepted" if response.accepted else "declined"

            assignment_update = connection.execute(
                """
                UPDATE rescue_assignments
                SET status = ?,
                    accepted_at = ?,
                    updated_at = ?
                WHERE assignment_id = ?
                  AND case_id = ?
                  AND replacement_driver_id = ?
                  AND status = 'call_queued'
                """,
                (
                    assignment_status,
                    now if response.accepted else None,
                    now,
                    assignment_id,
                    case_id,
                    driver_id,
                ),
            )

            if assignment_update.rowcount != 1:
                raise DriverConsentError("Assignment changed during response processing")

            call_update = connection.execute(
                """
                UPDATE rescue_calls
                SET status = 'completed',
                    ended_at = ?
                WHERE call_id = ?
                  AND status = 'in_progress'
                  AND provider_call_id = ?
                """,
                (now, call_id, provider_call_id),
            )

            if call_update.rowcount != 1:
                raise DriverConsentError("Call changed during response processing")

            connection.execute(
                """
                INSERT INTO rescue_events (
                    event_id,
                    case_id,
                    event_type,
                    payload_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    case_id,
                    "verified_driver_response",
                    json.dumps(
                        {
                            "assignment_id": assignment_id,
                            "driver_id": driver_id,
                            "call_id": call_id,
                            "accepted": response.accepted,
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )

            connection.commit()

            return DriverConsentResult(
                case_id=case_id,
                assignment_id=assignment_id,
                driver_id=driver_id,
                accepted=response.accepted,
                assignment_status=assignment_status,
                call_status="completed",
                recorded_at=now,
            )

        except sqlite3.Error as exc:
            if connection is not None:
                connection.rollback()
            raise DriverConsentError("Database error while recording driver response") from exc

        except Exception:
            if connection is not None:
                connection.rollback()
            raise

        finally:
            if connection is not None:
                connection.close()
