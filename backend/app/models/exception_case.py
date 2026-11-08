"""
DispatchResolve AI — Pickup Exception Case Model.

A pickup exception represents an operational problem
preventing a scheduled courier pickup from completing.

Features:
- Merchant-scoped exception cases
- Shipment linkage with tenant-safe foreign key
- Structured failure reasons
- Priority and severity
- SLA and escalation deadlines
- Assignment and investigation lifecycle
- Resolution only after verified pickup evidence
- Case reopening before terminal closure
- Concurrency-safe database updates

Important:
- This model does not contact couriers.
- AI classification happens in a separate service.
- SLA monitoring happens in a worker.
- All transitions must be authorized by the service layer.
- Every significant action must eventually create an audit event.
"""

from __future__ import annotations

import enum
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    MerchantOwnedModel,
    UUIDString,
    ensure_utc,
    utc_now,
)
from app.models.shipment import (
    Shipment,
    ShipmentStatus,
)

# ============================================================
# ENUMERATIONS
# ============================================================


class ExceptionCaseStatus(enum.StrEnum):
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_COURIER = "waiting_for_courier"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class ExceptionReason(enum.StrEnum):
    COURIER_NO_SHOW = "courier_no_show"
    COURIER_DELAYED = "courier_delayed"
    ADDRESS_ISSUE = "address_issue"
    PICKUP_RESCHEDULED = "pickup_rescheduled"
    AGENT_UNAVAILABLE = "agent_unavailable"
    CAPACITY_ISSUE = "capacity_issue"
    VEHICLE_BREAKDOWN = "vehicle_breakdown"
    WEATHER_DISRUPTION = "weather_disruption"
    MERCHANT_NOT_READY = "merchant_not_ready"
    CUSTOMER_UNAVAILABLE = "customer_unavailable"
    PROVIDER_SYSTEM_ERROR = "provider_system_error"
    OTHER = "other"
    UNKNOWN = "unknown"


class ExceptionSeverity(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExceptionSource(enum.StrEnum):
    AUTOMATED_MONITOR = "automated_monitor"
    MERCHANT_REPORTED = "merchant_reported"
    COURIER_REPORTED = "courier_reported"
    VOICE_AI = "voice_ai"
    SYSTEM_IMPORT = "system_import"
    DEMO_SIMULATION = "demo_simulation"


class ResolutionType(enum.StrEnum):
    PICKUP_VERIFIED = "pickup_verified"
    ADMINISTRATIVELY_CANCELLED = "administratively_cancelled"


# ============================================================
# STATUS TRANSITION RULES
# ============================================================

CASE_TRANSITIONS: dict[
    ExceptionCaseStatus,
    frozenset[ExceptionCaseStatus],
] = {
    ExceptionCaseStatus.OPEN: frozenset(
        {
            ExceptionCaseStatus.ASSIGNED,
            ExceptionCaseStatus.IN_PROGRESS,
            ExceptionCaseStatus.WAITING_FOR_COURIER,
            ExceptionCaseStatus.ESCALATED,
            ExceptionCaseStatus.RESOLVED,
            ExceptionCaseStatus.CANCELLED,
        }
    ),
    ExceptionCaseStatus.ASSIGNED: frozenset(
        {
            ExceptionCaseStatus.IN_PROGRESS,
            ExceptionCaseStatus.WAITING_FOR_COURIER,
            ExceptionCaseStatus.ESCALATED,
            ExceptionCaseStatus.RESOLVED,
            ExceptionCaseStatus.CANCELLED,
        }
    ),
    ExceptionCaseStatus.IN_PROGRESS: frozenset(
        {
            ExceptionCaseStatus.WAITING_FOR_COURIER,
            ExceptionCaseStatus.ESCALATED,
            ExceptionCaseStatus.RESOLVED,
            ExceptionCaseStatus.CANCELLED,
        }
    ),
    ExceptionCaseStatus.WAITING_FOR_COURIER: frozenset(
        {
            ExceptionCaseStatus.IN_PROGRESS,
            ExceptionCaseStatus.ESCALATED,
            ExceptionCaseStatus.RESOLVED,
            ExceptionCaseStatus.CANCELLED,
        }
    ),
    ExceptionCaseStatus.ESCALATED: frozenset(
        {
            ExceptionCaseStatus.IN_PROGRESS,
            ExceptionCaseStatus.WAITING_FOR_COURIER,
            ExceptionCaseStatus.RESOLVED,
            ExceptionCaseStatus.CANCELLED,
        }
    ),
    ExceptionCaseStatus.RESOLVED: frozenset(),
    ExceptionCaseStatus.CANCELLED: frozenset(),
}


# ============================================================
# DEFAULT SLA POLICY
# ============================================================

DEFAULT_SLA_MINUTES: dict[
    ExceptionSeverity,
    int,
] = {
    ExceptionSeverity.LOW: 240,
    ExceptionSeverity.MEDIUM: 120,
    ExceptionSeverity.HIGH: 60,
    ExceptionSeverity.CRITICAL: 30,
}


# ============================================================
# EXCEPTION CASE MODEL
# ============================================================


class ExceptionCase(MerchantOwnedModel):
    """
    A merchant-owned pickup failure investigation.

    Resolution requires a linked shipment with a
    verified pickup scan and PICKED_UP status.
    """

    __tablename__ = "exception_cases"

    __table_args__ = (
        UniqueConstraint(
            "id",
            "merchant_id",
            name="uq_exception_cases_id_merchant",
        ),
        UniqueConstraint(
            "merchant_id",
            "case_number",
            name="uq_exception_cases_merchant_number",
        ),
        ForeignKeyConstraint(
            ["shipment_id", "merchant_id"],
            ["shipments.id", "shipments.merchant_id"],
            name="fk_exception_cases_shipment_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "escalation_level >= 0 AND escalation_level <= 10",
            name="escalation_level_valid",
        ),
        CheckConstraint(
            "sla_minutes >= 0",
            name="sla_minutes_nonnegative",
        ),
        Index(
            "ix_exception_cases_merchant_status",
            "merchant_id",
            "status",
        ),
        Index(
            "ix_exception_cases_merchant_severity",
            "merchant_id",
            "severity",
        ),
        Index(
            "ix_exception_cases_merchant_sla",
            "merchant_id",
            "sla_deadline_at",
        ),
        Index(
            "ix_exception_cases_shipment",
            "shipment_id",
        ),
    )

    # --------------------------------------------------------
    # Tenant ownership
    # --------------------------------------------------------

    merchant_id: Mapped[str] = mapped_column(
        UUIDString(),
        ForeignKey(
            "merchants.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    shipment_id: Mapped[str] = mapped_column(
        UUIDString(),
        nullable=False,
    )

    case_number: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # --------------------------------------------------------
    # Classification
    # --------------------------------------------------------

    reason: Mapped[ExceptionReason] = mapped_column(
        SAEnum(
            ExceptionReason,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=64,
        ),
        nullable=False,
        default=ExceptionReason.UNKNOWN,
    )

    severity: Mapped[ExceptionSeverity] = mapped_column(
        SAEnum(
            ExceptionSeverity,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=ExceptionSeverity.MEDIUM,
    )

    source: Mapped[ExceptionSource] = mapped_column(
        SAEnum(
            ExceptionSource,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=40,
        ),
        nullable=False,
        default=ExceptionSource.AUTOMATED_MONITOR,
    )

    status: Mapped[ExceptionCaseStatus] = mapped_column(
        SAEnum(
            ExceptionCaseStatus,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=ExceptionCaseStatus.OPEN,
    )

    # --------------------------------------------------------
    # Description and ownership
    # --------------------------------------------------------

    summary: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    assigned_user_id: Mapped[str | None] = mapped_column(
        UUIDString(),
        nullable=True,
    )

    # --------------------------------------------------------
    # SLA and escalation
    # --------------------------------------------------------

    sla_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=120,
    )

    sla_deadline_at: Mapped[datetime | None] = mapped_column(nullable=True)

    escalation_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    escalated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    escalation_reason: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )

    # --------------------------------------------------------
    # Lifecycle timestamps
    # --------------------------------------------------------

    detected_at: Mapped[datetime] = mapped_column(
        default=utc_now,
        nullable=False,
    )

    assigned_at: Mapped[datetime | None] = mapped_column(nullable=True)

    first_action_at: Mapped[datetime | None] = mapped_column(nullable=True)

    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    cancelled_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # --------------------------------------------------------
    # Resolution metadata
    # --------------------------------------------------------

    resolution_type: Mapped[ResolutionType | None] = mapped_column(
        SAEnum(
            ResolutionType,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=40,
        ),
        nullable=True,
    )

    resolution_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # Case creation and SLA initialization
    # --------------------------------------------------------

    def initialize_sla(
        self,
        *,
        detected_at: datetime | None = None,
        sla_minutes: int | None = None,
    ) -> None:
        """
        Initialize SLA deadline.

        SLA = Service Level Agreement:
        maximum allowed response/resolution window.
        """

        start = ensure_utc(detected_at or self.detected_at or utc_now())

        duration = sla_minutes if sla_minutes is not None else DEFAULT_SLA_MINUTES[self.severity]

        if duration < 0:
            raise ValueError("SLA duration cannot be negative.")

        self.detected_at = start
        self.sla_minutes = duration
        self.sla_deadline_at = start + timedelta(minutes=duration)

    # --------------------------------------------------------
    # Status management
    # --------------------------------------------------------

    def can_transition_to(
        self,
        new_status: ExceptionCaseStatus,
    ) -> bool:
        current = self.status or ExceptionCaseStatus.OPEN
        return new_status in CASE_TRANSITIONS[current]

    def transition_to(
        self,
        new_status: ExceptionCaseStatus,
    ) -> None:
        current = self.status or ExceptionCaseStatus.OPEN

        if not self.can_transition_to(new_status):
            raise ValueError(f"Invalid case transition: {current.value} -> {new_status.value}")

        if new_status in {
            ExceptionCaseStatus.RESOLVED,
            ExceptionCaseStatus.CANCELLED,
        }:
            raise ValueError(
                "Use resolve_with_verified_pickup() or cancel_case() for terminal transitions."
            )

        self.status = new_status

        if new_status == ExceptionCaseStatus.IN_PROGRESS and self.first_action_at is None:
            self.first_action_at = utc_now()

    # --------------------------------------------------------
    # Assignment
    # --------------------------------------------------------

    def assign_to(self, user_id: str) -> None:
        """
        Assign a case to a user.

        The service layer must verify that the user
        belongs to the same merchant and is authorized.
        """

        if self.status in {
            ExceptionCaseStatus.RESOLVED,
            ExceptionCaseStatus.CANCELLED,
        }:
            raise ValueError("Terminal cases cannot be assigned.")

        if not user_id.strip():
            raise ValueError("Assigned user ID is required.")

        self.assigned_user_id = user_id
        self.assigned_at = utc_now()

        if self.status == ExceptionCaseStatus.OPEN:
            self.transition_to(ExceptionCaseStatus.ASSIGNED)

    # --------------------------------------------------------
    # Escalation
    # --------------------------------------------------------

    def escalate(
        self,
        *,
        reason: str,
    ) -> None:
        if self.status in {
            ExceptionCaseStatus.RESOLVED,
            ExceptionCaseStatus.CANCELLED,
        }:
            raise ValueError("Terminal cases cannot be escalated.")

        if self.escalation_level >= 10:
            raise ValueError("Maximum escalation level reached.")

        cleaned_reason = reason.strip()

        if not cleaned_reason:
            raise ValueError("Escalation reason is required.")

        self.escalation_level += 1
        self.escalated_at = utc_now()
        self.escalation_reason = cleaned_reason

        if self.status != ExceptionCaseStatus.ESCALATED:
            self.transition_to(ExceptionCaseStatus.ESCALATED)

    # --------------------------------------------------------
    # SLA evaluation
    # --------------------------------------------------------

    def is_sla_breached(
        self,
        *,
        now: datetime | None = None,
    ) -> bool:
        if self.status in {
            ExceptionCaseStatus.RESOLVED,
            ExceptionCaseStatus.CANCELLED,
        }:
            return False

        if self.sla_deadline_at is None:
            return False

        return ensure_utc(now or utc_now()) > ensure_utc(self.sla_deadline_at)

    # --------------------------------------------------------
    # Verified resolution
    # --------------------------------------------------------

    def resolve_with_verified_pickup(
        self,
        *,
        shipment: Shipment,
        note: str = "Pickup confirmed by verified scan.",
    ) -> None:
        """
        Close a case only after verified pickup.

        The service layer must fetch the shipment from
        the database and verify the scan's authenticity.
        """

        if self.status in {
            ExceptionCaseStatus.RESOLVED,
            ExceptionCaseStatus.CANCELLED,
        }:
            raise ValueError("Terminal cases cannot be resolved again.")

        if shipment.id != self.shipment_id or shipment.merchant_id != self.merchant_id:
            raise ValueError("Shipment does not belong to this case.")

        if shipment.status != ShipmentStatus.PICKED_UP:
            raise ValueError("Shipment has not been picked up.")

        if not shipment.has_pickup_evidence:
            raise ValueError("Verified pickup evidence is required.")

        self.status = ExceptionCaseStatus.RESOLVED
        self.resolution_type = ResolutionType.PICKUP_VERIFIED
        self.resolution_note = note.strip()
        self.resolved_at = utc_now()

    # --------------------------------------------------------
    # Administrative cancellation
    # --------------------------------------------------------

    def cancel_case(self, *, reason: str) -> None:
        """
        Cancel an invalid or duplicate case.

        Cancellation is not counted as a successful pickup.
        Authorization and audit logging are required.
        """

        if self.status in {
            ExceptionCaseStatus.RESOLVED,
            ExceptionCaseStatus.CANCELLED,
        }:
            raise ValueError("Terminal cases cannot be cancelled.")

        cleaned_reason = reason.strip()

        if not cleaned_reason:
            raise ValueError("Cancellation reason is required.")

        self.status = ExceptionCaseStatus.CANCELLED
        self.resolution_type = ResolutionType.ADMINISTRATIVELY_CANCELLED
        self.resolution_note = cleaned_reason
        self.cancelled_at = utc_now()

    # --------------------------------------------------------
    # Derived state
    # --------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self.status not in {
            ExceptionCaseStatus.RESOLVED,
            ExceptionCaseStatus.CANCELLED,
        }

    @property
    def is_escalated(self) -> bool:
        return self.escalation_level > 0

    # --------------------------------------------------------
    # Safe representation
    # --------------------------------------------------------

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "merchant_id": self.merchant_id,
            "shipment_id": self.shipment_id,
            "case_number": self.case_number,
            "status": (self.status.value if self.status is not None else None),
            "reason": (self.reason.value if self.reason is not None else None),
            "severity": (self.severity.value if self.severity is not None else None),
            "summary": self.summary,
            "escalation_level": self.escalation_level,
            "is_open": self.is_open,
        }

    def __repr__(self) -> str:
        return (
            f"ExceptionCase(id={self.id!r}, "
            f"case_number={self.case_number!r}, "
            f"status={self.status!r})"
        )


__all__ = [
    "ExceptionCase",
    "ExceptionCaseStatus",
    "ExceptionReason",
    "ExceptionSeverity",
    "ExceptionSource",
    "ResolutionType",
    "CASE_TRANSITIONS",
    "DEFAULT_SLA_MINUTES",
]
