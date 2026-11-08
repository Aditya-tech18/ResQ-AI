"""Fail-closed approval policy for AI-assisted parcel rescue.

Responsibilities:
- Validate explicit replacement-driver acceptance.
- Reject conditional, ambiguous, or declined offers.
- Bind consent to a specific rescue case, driver and assignment.
- Reject expired or future-dated consent.
- Require verified dispatcher approval before authorization.
- Return machine-readable decisions suitable for audit logging.

Non-responsibilities:
- Authenticate users.
- Verify signatures or ownership of consent evidence.
- Persist approvals or assignments.
- Perform database transactions.

The caller must supply trusted, independently verified context.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any


class ApprovalStatus(StrEnum):
    BLOCKED = "BLOCKED"
    AWAITING_DISPATCHER_APPROVAL = "AWAITING_DISPATCHER_APPROVAL"
    AUTHORIZED_FOR_COMMIT = "AUTHORIZED_FOR_COMMIT"


class ApprovalReason(StrEnum):
    INVALID_DECISION = "INVALID_DECISION"
    DRIVER_NOT_ACCEPTED = "DRIVER_NOT_ACCEPTED"
    INVALID_CONTEXT = "INVALID_CONTEXT"
    CONTEXT_MISMATCH = "CONTEXT_MISMATCH"
    INVALID_CONSENT_TIME = "INVALID_CONSENT_TIME"
    CONSENT_EXPIRED = "CONSENT_EXPIRED"
    CONSENT_IN_FUTURE = "CONSENT_IN_FUTURE"
    DISPATCHER_APPROVAL_REQUIRED = "DISPATCHER_APPROVAL_REQUIRED"
    AUTHORIZED = "AUTHORIZED"


@dataclass(frozen=True, slots=True)
class RescueApprovalContext:
    """Trusted identifiers for the assignment under review."""

    case_id: str
    driver_id: str
    assignment_id: str
    consent_recorded_at: datetime
    dispatcher_id: str | None = None
    dispatcher_approved_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ApprovalResult:
    can_commit: bool
    status: ApprovalStatus
    reason_code: ApprovalReason
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "can_commit": self.can_commit,
            "status": self.status.value,
            "reason_code": self.reason_code.value,
            "reason": self.reason,
        }


class AIRescueApprovalGate:
    """Deterministic, fail-closed rescue authorization policy."""

    DEFAULT_CONSENT_TTL = timedelta(minutes=30)
    MAX_CLOCK_SKEW = timedelta(seconds=30)

    @staticmethod
    def _result(
        status: ApprovalStatus,
        reason_code: ApprovalReason,
        reason: str,
    ) -> dict[str, Any]:
        return ApprovalResult(
            can_commit=status is ApprovalStatus.AUTHORIZED_FOR_COMMIT,
            status=status,
            reason_code=reason_code,
            reason=reason,
        ).to_dict()

    @staticmethod
    def _valid_identifier(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _utc(value: datetime) -> datetime | None:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(UTC)

    @classmethod
    def evaluate(
        cls,
        decision: Mapping[str, Any],
        *,
        dispatcher_approved: bool = False,
        context: RescueApprovalContext | None = None,
        now: datetime | None = None,
        consent_ttl: timedelta | None = None,
    ) -> dict[str, Any]:
        """Evaluate whether a proposed rescue assignment may proceed.

        Compatibility:
            Calls without context retain the original decision-only
            validation behavior, but never authorize a database commit.

        Security:
            The caller must verify dispatcher identity and approval,
            consent provenance, assignment ownership, and current DB state.
        """

        blocked = ApprovalStatus.BLOCKED

        if not isinstance(decision, Mapping):
            return cls._result(
                blocked,
                ApprovalReason.INVALID_DECISION,
                "Decision must be a mapping.",
            )

        accepted = (
            decision.get("decision") == "READY_FOR_ASSIGNMENT"
            and decision.get("intent") == "rescue_accept"
            and decision.get("explicit_confirmation") is True
            and decision.get("needs_clarification") is False
        )

        if not accepted:
            return cls._result(
                blocked,
                ApprovalReason.DRIVER_NOT_ACCEPTED,
                "Driver has not explicitly accepted this assignment.",
            )

        # Compatibility with the earlier API: a positive driver response
        # without trusted context is pending, never commit-authorized.
        if context is None:
            return cls._result(
                ApprovalStatus.AWAITING_DISPATCHER_APPROVAL,
                ApprovalReason.INVALID_CONTEXT,
                "Trusted case, driver and assignment context is required.",
            )

        if not isinstance(context, RescueApprovalContext):
            return cls._result(
                blocked,
                ApprovalReason.INVALID_CONTEXT,
                "Invalid rescue approval context.",
            )

        identifiers = (
            context.case_id,
            context.driver_id,
            context.assignment_id,
        )

        if not all(cls._valid_identifier(item) for item in identifiers):
            return cls._result(
                blocked,
                ApprovalReason.INVALID_CONTEXT,
                "Case, driver and assignment IDs are required.",
            )

        # These fields must come from a trusted consent record,
        # not directly from an untrusted LLM response.
        expected = {
            "case_id": context.case_id,
            "driver_id": context.driver_id,
            "assignment_id": context.assignment_id,
        }

        for field, value in expected.items():
            if decision.get(field) != value:
                return cls._result(
                    blocked,
                    ApprovalReason.CONTEXT_MISMATCH,
                    f"Decision does not match trusted {field}.",
                )

        recorded_at = cls._utc(context.consent_recorded_at)
        current_time = cls._utc(now or datetime.now(UTC))

        if recorded_at is None or current_time is None:
            return cls._result(
                blocked,
                ApprovalReason.INVALID_CONSENT_TIME,
                "Consent timestamps must be timezone-aware.",
            )

        ttl = cls.DEFAULT_CONSENT_TTL if consent_ttl is None else consent_ttl

        if not isinstance(ttl, timedelta) or ttl <= timedelta(0):
            return cls._result(
                blocked,
                ApprovalReason.INVALID_CONSENT_TIME,
                "Consent TTL must be positive.",
            )

        if recorded_at > current_time + cls.MAX_CLOCK_SKEW:
            return cls._result(
                blocked,
                ApprovalReason.CONSENT_IN_FUTURE,
                "Consent timestamp is in the future.",
            )

        if current_time - recorded_at > ttl:
            return cls._result(
                blocked,
                ApprovalReason.CONSENT_EXPIRED,
                "Driver consent has expired.",
            )

        if not dispatcher_approved:
            return cls._result(
                ApprovalStatus.AWAITING_DISPATCHER_APPROVAL,
                ApprovalReason.DISPATCHER_APPROVAL_REQUIRED,
                "Driver accepted; dispatcher approval is required.",
            )

        if not cls._valid_identifier(context.dispatcher_id):
            return cls._result(
                blocked,
                ApprovalReason.INVALID_CONTEXT,
                "Verified dispatcher identity is required.",
            )

        approved_at = (
            cls._utc(context.dispatcher_approved_at)
            if context.dispatcher_approved_at is not None
            else None
        )

        if approved_at is None:
            return cls._result(
                blocked,
                ApprovalReason.INVALID_CONSENT_TIME,
                "Dispatcher approval timestamp is required.",
            )

        if approved_at < recorded_at:
            return cls._result(
                blocked,
                ApprovalReason.INVALID_CONSENT_TIME,
                "Dispatcher approval cannot precede driver consent.",
            )

        if approved_at > current_time + cls.MAX_CLOCK_SKEW:
            return cls._result(
                blocked,
                ApprovalReason.INVALID_CONSENT_TIME,
                "Dispatcher approval timestamp is in the future.",
            )

        return cls._result(
            ApprovalStatus.AUTHORIZED_FOR_COMMIT,
            ApprovalReason.AUTHORIZED,
            "Driver consent and dispatcher approval passed policy checks.",
        )
