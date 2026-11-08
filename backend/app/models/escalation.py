"""
DispatchResolve AI - Escalation Model.

Tracks escalations of courier pickup exception cases.

An escalation can be acknowledged by a supervisor,
but successful resolution requires verified pickup.

Notification delivery and actor authorization are
handled by separate services.
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
from app.models.exception_case import ExceptionCase
from app.models.shipment import Shipment, ShipmentStatus


class EscalationStatus(enum.StrEnum):
    PENDING = "pending"
    NOTIFIED = "notified"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class EscalationReason(enum.StrEnum):
    PICKUP_OVERDUE = "pickup_overdue"
    COMMITMENT_MISSED = "commitment_missed"
    SLA_BREACHED = "sla_breached"
    REPEATED_FAILURE = "repeated_failure"
    COURIER_UNREACHABLE = "courier_unreachable"
    MANUAL_ESCALATION = "manual_escalation"


class EscalationTarget(enum.StrEnum):
    DISPATCHER = "dispatcher"
    COURIER_SUPERVISOR = "courier_supervisor"
    OPERATIONS_MANAGER = "operations_manager"
    MERCHANT_ADMIN = "merchant_admin"


class Escalation(MerchantOwnedModel):
    """Merchant-scoped escalation linked to an exception case."""

    __tablename__ = "escalations"

    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "escalation_number",
            name="uq_escalations_merchant_number",
        ),
        ForeignKeyConstraint(
            ["exception_case_id", "merchant_id"],
            ["exception_cases.id", "exception_cases.merchant_id"],
            name="fk_escalations_case_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "level >= 1 AND level <= 10",
            name="escalation_level_range",
        ),
        CheckConstraint(
            "response_sla_minutes >= 0",
            name="escalation_response_sla_nonnegative",
        ),
        Index(
            "ix_escalations_merchant_status",
            "merchant_id",
            "status",
        ),
        Index(
            "ix_escalations_case_level",
            "exception_case_id",
            "level",
        ),
        Index(
            "ix_escalations_response_deadline",
            "merchant_id",
            "response_due_at",
        ),
    )

    merchant_id: Mapped[str] = mapped_column(
        UUIDString(),
        ForeignKey("merchants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    exception_case_id: Mapped[str] = mapped_column(
        UUIDString(),
        nullable=False,
    )

    escalation_number: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    status: Mapped[EscalationStatus] = mapped_column(
        SAEnum(
            EscalationStatus,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=EscalationStatus.PENDING,
    )

    reason: Mapped[EscalationReason] = mapped_column(
        SAEnum(
            EscalationReason,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=40,
        ),
        nullable=False,
    )

    target: Mapped[EscalationTarget] = mapped_column(
        SAEnum(
            EscalationTarget,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=40,
        ),
        nullable=False,
    )

    summary: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )

    details: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # User identity must be validated against the
    # merchant and permissions by the service layer.
    assigned_user_id: Mapped[str | None] = mapped_column(
        UUIDString(),
        nullable=True,
    )

    response_sla_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
    )

    response_due_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    triggered_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=utc_now,
    )

    notified_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    acknowledged_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    resolution_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    cancellation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    @classmethod
    def create(
        cls,
        *,
        merchant_id: str,
        exception_case_id: str,
        escalation_number: str,
        reason: EscalationReason,
        target: EscalationTarget,
        summary: str,
        level: int = 1,
        response_sla_minutes: int = 30,
        triggered_at: datetime | None = None,
        assigned_user_id: str | None = None,
    ) -> Escalation:
        if not 1 <= level <= 10:
            raise ValueError("Escalation level must be between 1 and 10.")

        if response_sla_minutes < 0:
            raise ValueError("Response SLA cannot be negative.")

        if not escalation_number.strip():
            raise ValueError("Escalation number is required.")

        if not summary.strip():
            raise ValueError("Escalation summary is required.")

        start = ensure_utc(triggered_at or utc_now())

        return cls(
            merchant_id=merchant_id,
            exception_case_id=exception_case_id,
            escalation_number=escalation_number.strip(),
            reason=reason,
            target=target,
            summary=summary.strip(),
            level=level,
            response_sla_minutes=response_sla_minutes,
            triggered_at=start,
            response_due_at=start + timedelta(minutes=response_sla_minutes),
            assigned_user_id=assigned_user_id,
            status=EscalationStatus.PENDING,
        )

    def mark_notified(
        self,
        *,
        at: datetime | None = None,
    ) -> None:
        if self.status != EscalationStatus.PENDING:
            raise ValueError("Only pending escalations can be notified.")

        self.status = EscalationStatus.NOTIFIED
        self.notified_at = ensure_utc(at or utc_now())

    def acknowledge(
        self,
        *,
        at: datetime | None = None,
    ) -> None:
        if self.status not in {
            EscalationStatus.PENDING,
            EscalationStatus.NOTIFIED,
        }:
            raise ValueError("Escalation cannot be acknowledged.")

        self.status = EscalationStatus.ACKNOWLEDGED
        self.acknowledged_at = ensure_utc(at or utc_now())

    def is_response_overdue(
        self,
        *,
        now: datetime | None = None,
    ) -> bool:
        if self.status not in {
            EscalationStatus.PENDING,
            EscalationStatus.NOTIFIED,
        }:
            return False

        if self.response_due_at is None:
            return False

        return ensure_utc(now or utc_now()) > ensure_utc(self.response_due_at)

    def resolve_with_verified_pickup(
        self,
        *,
        case: ExceptionCase,
        shipment: Shipment,
        note: str = "Verified pickup completed.",
    ) -> None:
        if self.status in {
            EscalationStatus.RESOLVED,
            EscalationStatus.CANCELLED,
        }:
            raise ValueError("Terminal escalation cannot be resolved.")

        if case.id != self.exception_case_id or case.merchant_id != self.merchant_id:
            raise ValueError("Exception case does not match escalation.")

        if shipment.id != case.shipment_id or shipment.merchant_id != self.merchant_id:
            raise ValueError("Shipment does not match escalation.")

        if shipment.status != ShipmentStatus.PICKED_UP or not shipment.has_pickup_evidence:
            raise ValueError("Verified pickup evidence is required.")

        if not note.strip():
            raise ValueError("Resolution note is required.")

        self.status = EscalationStatus.RESOLVED
        self.resolved_at = utc_now()
        self.resolution_note = note.strip()

    def cancel(self, *, reason: str) -> None:
        if self.status in {
            EscalationStatus.RESOLVED,
            EscalationStatus.CANCELLED,
        }:
            raise ValueError("Terminal escalation cannot be cancelled.")

        if not reason.strip():
            raise ValueError("Cancellation reason is required.")

        self.status = EscalationStatus.CANCELLED
        self.cancelled_at = utc_now()
        self.cancellation_reason = reason.strip()

    @property
    def is_active(self) -> bool:
        return self.status not in {
            EscalationStatus.RESOLVED,
            EscalationStatus.CANCELLED,
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "merchant_id": self.merchant_id,
            "exception_case_id": self.exception_case_id,
            "escalation_number": self.escalation_number,
            "level": self.level,
            "status": self.status.value,
            "reason": self.reason.value,
            "target": self.target.value,
            "summary": self.summary,
            "is_active": self.is_active,
        }


__all__ = [
    "Escalation",
    "EscalationStatus",
    "EscalationReason",
    "EscalationTarget",
]
