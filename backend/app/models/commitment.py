"""
DispatchResolve AI — Courier Pickup Commitment Model.

Tracks promises made by couriers about pickup timing.

A courier promise is not pickup confirmation.

Only a verified shipment pickup can fulfill a promise.

Includes:
- Merchant isolation
- Pickup deadlines
- Reminder eligibility
- Missed commitment detection
- AI extraction metadata
- Verified fulfillment
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
from app.models.shipment import Shipment, ShipmentStatus


class CommitmentStatus(enum.StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FULFILLED = "fulfilled"
    MISSED = "missed"
    CANCELLED = "cancelled"


class CommitmentSource(enum.StrEnum):
    COURIER_VOICE = "courier_voice"
    COURIER_TEXT = "courier_text"
    DISPATCHER_ENTRY = "dispatcher_entry"
    PROVIDER_API = "provider_api"
    DEMO_SIMULATION = "demo_simulation"


class Commitment(MerchantOwnedModel):
    """
    Courier pickup promise linked to a shipment.

    Tenant-safe foreign keys prevent cross-merchant
    shipment and exception-case references.
    """

    __tablename__ = "commitments"

    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "commitment_number",
            name="uq_commitments_merchant_number",
        ),
        ForeignKeyConstraint(
            ["shipment_id", "merchant_id"],
            ["shipments.id", "shipments.merchant_id"],
            name="fk_commitments_shipment_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["exception_case_id", "merchant_id"],
            [
                "exception_cases.id",
                "exception_cases.merchant_id",
            ],
            name="fk_commitments_case_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "extraction_confidence IS NULL OR "
            "(extraction_confidence >= 0 "
            "AND extraction_confidence <= 100)",
            name="commitment_confidence_range",
        ),
        CheckConstraint(
            "reminder_minutes_before >= 0",
            name="commitment_reminder_nonnegative",
        ),
        Index(
            "ix_commitments_merchant_status",
            "merchant_id",
            "status",
        ),
        Index(
            "ix_commitments_merchant_due",
            "merchant_id",
            "promised_pickup_at",
        ),
    )

    merchant_id: Mapped[str] = mapped_column(
        UUIDString(),
        ForeignKey("merchants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    shipment_id: Mapped[str] = mapped_column(
        UUIDString(),
        nullable=False,
    )

    exception_case_id: Mapped[str | None] = mapped_column(
        UUIDString(),
        nullable=True,
    )

    commitment_number: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    status: Mapped[CommitmentStatus] = mapped_column(
        SAEnum(
            CommitmentStatus,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=CommitmentStatus.PENDING,
    )

    source: Mapped[CommitmentSource] = mapped_column(
        SAEnum(
            CommitmentSource,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=CommitmentSource.DISPATCHER_ENTRY,
    )

    promised_pickup_at: Mapped[datetime] = mapped_column(
        nullable=False,
    )

    recorded_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=utc_now,
    )

    confirmed_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    fulfilled_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    missed_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    courier_agent_id: Mapped[str | None] = mapped_column(
        UUIDString(),
        nullable=True,
    )

    original_statement: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    language_code: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )

    extraction_confidence: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    extraction_model: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    reminder_minutes_before: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=15,
    )

    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    def confirm(self) -> None:
        if self.status != CommitmentStatus.PENDING:
            raise ValueError("Only pending commitments can be confirmed.")

        self.status = CommitmentStatus.CONFIRMED
        self.confirmed_at = utc_now()

    def is_overdue(
        self,
        *,
        now: datetime | None = None,
    ) -> bool:
        if self.status not in {
            CommitmentStatus.PENDING,
            CommitmentStatus.CONFIRMED,
        }:
            return False

        current = ensure_utc(now or utc_now())

        return current > ensure_utc(self.promised_pickup_at)

    def mark_missed(
        self,
        *,
        now: datetime | None = None,
    ) -> None:
        current = ensure_utc(now or utc_now())

        if not self.is_overdue(now=current):
            raise ValueError("Commitment has not become overdue.")

        self.status = CommitmentStatus.MISSED
        self.missed_at = current

    def fulfill_with_verified_pickup(
        self,
        *,
        shipment: Shipment,
    ) -> None:
        """
        A promise is fulfilled only if the pickup scan
        was recorded by the promised deadline.

        The service layer must authenticate the scan.
        """

        if self.status not in {
            CommitmentStatus.PENDING,
            CommitmentStatus.CONFIRMED,
        }:
            raise ValueError("Commitment cannot be fulfilled from its current status.")

        if shipment.id != self.shipment_id or shipment.merchant_id != self.merchant_id:
            raise ValueError("Shipment does not match commitment.")

        if shipment.status != ShipmentStatus.PICKED_UP or not shipment.has_pickup_evidence:
            raise ValueError("Verified pickup evidence is required.")

        scan_time = ensure_utc(shipment.pickup_scanned_at)

        if scan_time > ensure_utc(self.promised_pickup_at):
            raise ValueError("Pickup occurred after promised deadline.")

        self.status = CommitmentStatus.FULFILLED
        self.fulfilled_at = scan_time

    def cancel(self, *, reason: str) -> None:
        if self.status not in {
            CommitmentStatus.PENDING,
            CommitmentStatus.CONFIRMED,
        }:
            raise ValueError("Only open commitments can be cancelled.")

        if not reason.strip():
            raise ValueError("Cancellation reason is required.")

        self.status = CommitmentStatus.CANCELLED
        self.cancelled_at = utc_now()
        self.notes = reason.strip()

    def should_send_reminder(
        self,
        *,
        now: datetime | None = None,
    ) -> bool:
        if self.status not in {
            CommitmentStatus.PENDING,
            CommitmentStatus.CONFIRMED,
        }:
            return False

        if self.reminder_sent_at is not None:
            return False

        current = ensure_utc(now or utc_now())
        deadline = ensure_utc(self.promised_pickup_at)

        reminder_start = deadline - timedelta(minutes=self.reminder_minutes_before)

        return reminder_start <= current < deadline

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "merchant_id": self.merchant_id,
            "shipment_id": self.shipment_id,
            "exception_case_id": self.exception_case_id,
            "commitment_number": self.commitment_number,
            "status": (self.status.value if self.status is not None else None),
            "source": (self.source.value if self.source is not None else None),
            "promised_pickup_at": (
                self.promised_pickup_at.isoformat() if self.promised_pickup_at else None
            ),
        }


__all__ = [
    "Commitment",
    "CommitmentStatus",
    "CommitmentSource",
]
