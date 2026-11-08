"""Validate rescue call context before processing AI driver responses.

This service validates database relationships and operational state.
Telephony webhook authentication and caller identity verification must
happen separately in a trusted provider integration.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.services.ai_rescue_conversation_adapter import (
    VerifiedConversationContext,
)


class RescueCallContextError(ValueError):
    """The supplied rescue call context is invalid or unavailable."""


@dataclass(frozen=True, slots=True)
class RescueCallLookup:
    case_id: str
    assignment_id: str
    driver_id: str
    call_id: str


class RescueCallContextService:
    """Read-only validator for active emergency rescue conversations."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    @staticmethod
    def _validate_identifier(value: object, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise RescueCallContextError(f"{field} must be a non-empty string")
        return value.strip()

    def resolve(
        self,
        lookup: RescueCallLookup,
        *,
        provider_event_verified: bool,
        driver_identity_verified: bool,
    ) -> VerifiedConversationContext:
        """Return a context only for a matching, active rescue call.

        Both verification flags must originate from a trusted
        authentication layer, never from an untrusted request body
        or an AI-generated response.

        This method does not authenticate a telephony provider,
        verify a caller's identity, or persist driver consent.
        """
        if not isinstance(lookup, RescueCallLookup):
            raise RescueCallContextError("Invalid call lookup")

        call_id = self._validate_identifier(lookup.call_id, "call_id")
        case_id = self._validate_identifier(lookup.case_id, "case_id")
        assignment_id = self._validate_identifier(lookup.assignment_id, "assignment_id")
        driver_id = self._validate_identifier(lookup.driver_id, "driver_id")

        if provider_event_verified is not True:
            raise RescueCallContextError("Telephony event has not been authenticated")

        if driver_identity_verified is not True:
            raise RescueCallContextError("Driver identity has not been verified")

        if not self.db_path.is_file():
            raise RescueCallContextError("Rescue workflow database is unavailable")

        try:
            with sqlite3.connect(
                f"file:{self.db_path.resolve()}?mode=ro",
                uri=True,
                timeout=5,
            ) as db:
                db.row_factory = sqlite3.Row

                row = db.execute(
                    """
                    SELECT
                        c.call_id,
                        c.case_id,
                        c.assignment_id,
                        c.driver_id,
                        c.status AS call_status,
                        a.status AS assignment_status,
                        a.replacement_driver_id,
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

        except sqlite3.Error as exc:
            raise RescueCallContextError("Unable to verify rescue call state") from exc

        if row is None:
            raise RescueCallContextError("Call, driver, case, or assignment mismatch")

        if row["call_status"] != "in_progress":
            raise RescueCallContextError("Rescue call is not actively connected")

        if row["assignment_status"] != "call_queued":
            raise RescueCallContextError("Assignment is not awaiting a driver response")

        if row["case_status"] != "calling":
            raise RescueCallContextError("Rescue case is not accepting call responses")

        return VerifiedConversationContext(
            case_id=row["case_id"],
            assignment_id=row["assignment_id"],
            driver_id=row["driver_id"],
            call_id=row["call_id"],
            identity_verified=True,
            call_active=True,
        )
