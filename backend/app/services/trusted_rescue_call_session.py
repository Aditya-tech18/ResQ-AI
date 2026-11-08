"""Trusted rescue call-session verification.

Purpose
-------
Bind a rescue conversation to existing database records before
allowing AI interpretation to participate in an operational workflow.

Security boundary
-----------------
The caller must already be authenticated by a trusted integration.
This service verifies database relationships and lifecycle state.
It does not authenticate telephone callers, validate provider
signatures, or authorize shipment transfer.

The service is read-only and fails closed.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class SessionVerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    RELATIONSHIP_MISMATCH = "RELATIONSHIP_MISMATCH"
    INVALID_STATE = "INVALID_STATE"
    DATABASE_ERROR = "DATABASE_ERROR"


@dataclass(frozen=True, slots=True)
class TrustedCallIdentity:
    """Identity asserted by an authenticated upstream integration.

    Do not construct this object directly from public JSON input.
    """

    case_id: str
    assignment_id: str
    driver_id: str
    call_id: str

    # True only after upstream authentication has succeeded.
    identity_verified: bool

    # Source identifies the trusted authentication mechanism.
    verification_source: str


@dataclass(frozen=True, slots=True)
class SessionVerificationResult:
    verified: bool
    status: SessionVerificationStatus
    reason: str
    case_id: str | None = None
    assignment_id: str | None = None
    driver_id: str | None = None
    call_id: str | None = None
    call_language: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "status": self.status.value,
            "reason": self.reason,
            "case_id": self.case_id,
            "assignment_id": self.assignment_id,
            "driver_id": self.driver_id,
            "call_id": self.call_id,
            "call_language": self.call_language,
        }


class TrustedRescueCallSessionService:
    """Validate the persisted relationships of an active rescue call."""

    ACTIVE_CALL_STATES = frozenset({"queued", "in_progress"})
    ACTIVE_ASSIGNMENT_STATES = frozenset({"call_queued"})
    ACTIVE_CASE_STATES = frozenset({"calling"})

    TRUSTED_SOURCES = frozenset(
        {
            "verified_provider_webhook",
            "authenticated_driver_session",
        }
    )

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    @staticmethod
    def _valid_identifier(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @classmethod
    def _result(
        cls,
        status: SessionVerificationStatus,
        reason: str,
        *,
        identity: TrustedCallIdentity | None = None,
        call_language: str | None = None,
    ) -> dict[str, Any]:
        verified = status is SessionVerificationStatus.VERIFIED

        return SessionVerificationResult(
            verified=verified,
            status=status,
            reason=reason,
            case_id=identity.case_id if verified and identity else None,
            assignment_id=(identity.assignment_id if verified and identity else None),
            driver_id=identity.driver_id if verified and identity else None,
            call_id=identity.call_id if verified and identity else None,
            call_language=call_language if verified else None,
        ).to_dict()

    def verify(
        self,
        identity: TrustedCallIdentity,
    ) -> dict[str, Any]:
        """Verify trusted identity against current workflow records.

        A VERIFIED result means the supplied authenticated identity
        matches an active database call and assignment.

        It does not mean the driver accepted the rescue request.
        """

        if not isinstance(identity, TrustedCallIdentity):
            return self._result(
                SessionVerificationStatus.INVALID_INPUT,
                "TrustedCallIdentity is required.",
            )

        identifiers = (
            identity.case_id,
            identity.assignment_id,
            identity.driver_id,
            identity.call_id,
        )

        if not all(self._valid_identifier(value) for value in identifiers):
            return self._result(
                SessionVerificationStatus.INVALID_INPUT,
                "All rescue identifiers must be nonempty strings.",
            )

        if identity.identity_verified is not True:
            return self._result(
                SessionVerificationStatus.INVALID_INPUT,
                "Upstream driver authentication is required.",
            )

        if identity.verification_source not in self.TRUSTED_SOURCES:
            return self._result(
                SessionVerificationStatus.INVALID_INPUT,
                "Untrusted identity verification source.",
            )

        if not self.db_path.is_file():
            return self._result(
                SessionVerificationStatus.DATABASE_ERROR,
                "Rescue database is unavailable.",
            )

        try:
            connection = sqlite3.connect(
                f"file:{self.db_path.resolve()}?mode=ro",
                uri=True,
                timeout=5,
            )
            connection.row_factory = sqlite3.Row

            try:
                row = connection.execute(
                    """
                    SELECT
                        c.call_id,
                        c.case_id AS call_case_id,
                        c.assignment_id AS call_assignment_id,
                        c.driver_id AS call_driver_id,
                        c.status AS call_status,
                        c.current_language,
                        a.case_id AS assignment_case_id,
                        a.replacement_driver_id,
                        a.status AS assignment_status,
                        r.status AS case_status
                    FROM rescue_calls AS c
                    JOIN rescue_assignments AS a
                      ON a.assignment_id = c.assignment_id
                    JOIN rescue_cases AS r
                      ON r.case_id = c.case_id
                    WHERE c.call_id = ?
                    LIMIT 1
                    """,
                    (identity.call_id,),
                ).fetchone()
            finally:
                connection.close()

        except sqlite3.Error:
            return self._result(
                SessionVerificationStatus.DATABASE_ERROR,
                "Unable to verify rescue call state.",
            )

        if row is None:
            return self._result(
                SessionVerificationStatus.NOT_FOUND,
                "Rescue call does not exist.",
            )

        relationships_match = (
            row["call_id"] == identity.call_id
            and row["call_case_id"] == identity.case_id
            and row["call_assignment_id"] == identity.assignment_id
            and row["call_driver_id"] == identity.driver_id
            and row["assignment_case_id"] == identity.case_id
            and row["replacement_driver_id"] == identity.driver_id
        )

        if not relationships_match:
            return self._result(
                SessionVerificationStatus.RELATIONSHIP_MISMATCH,
                "Call, case, assignment, and driver do not match.",
            )

        if (
            row["call_status"] not in self.ACTIVE_CALL_STATES
            or row["assignment_status"] not in self.ACTIVE_ASSIGNMENT_STATES
            or row["case_status"] not in self.ACTIVE_CASE_STATES
        ):
            return self._result(
                SessionVerificationStatus.INVALID_STATE,
                "Rescue call is not eligible for driver response.",
            )

        return self._result(
            SessionVerificationStatus.VERIFIED,
            "Active rescue call relationships verified.",
            identity=identity,
            call_language=row["current_language"],
        )
