"""
DispatchResolve AI — Shipment and Pickup Tracking Model.

Stores:
- Merchant-owned shipments
- Courier company and agent assignments
- Scheduled pickup windows
- Shipment lifecycle status
- Pickup exceptions and deadlines
- Verified pickup scan evidence
- External shipment references
- Concurrency-safe updates

Security and integrity:
- Tenant-safe composite foreign keys
- No automatic closure from verbal courier promises
- Pickup completion requires scan evidence
- Shipment transitions are validated
- No real customer PII required for demo data

Future modules:
- Shipment events and audit trails
- Pickup exception cases
- Courier commitments
- Escalation workflows
- Provider webhook verification
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
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

# ============================================================
# SHIPMENT STATUS
# ============================================================


class ShipmentStatus(enum.StrEnum):
    CREATED = "created"
    SCHEDULED = "scheduled"
    AWAITING_PICKUP = "awaiting_pickup"
    PICKUP_EXCEPTION = "pickup_exception"
    PICKED_UP = "picked_up"
    CANCELLED = "cancelled"


class PickupEvidenceType(enum.StrEnum):
    PROVIDER_SCAN = "provider_scan"
    VERIFIED_WEBHOOK = "verified_webhook"
    MANUAL_VERIFIED = "manual_verified"


class ShipmentPriority(enum.StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================
# STATUS TRANSITIONS
# ============================================================

ALLOWED_TRANSITIONS: dict[
    ShipmentStatus,
    frozenset[ShipmentStatus],
] = {
    ShipmentStatus.CREATED: frozenset(
        {
            ShipmentStatus.SCHEDULED,
            ShipmentStatus.CANCELLED,
        }
    ),
    ShipmentStatus.SCHEDULED: frozenset(
        {
            ShipmentStatus.AWAITING_PICKUP,
            ShipmentStatus.PICKUP_EXCEPTION,
            ShipmentStatus.PICKED_UP,
            ShipmentStatus.CANCELLED,
        }
    ),
    ShipmentStatus.AWAITING_PICKUP: frozenset(
        {
            ShipmentStatus.PICKUP_EXCEPTION,
            ShipmentStatus.PICKED_UP,
            ShipmentStatus.CANCELLED,
        }
    ),
    ShipmentStatus.PICKUP_EXCEPTION: frozenset(
        {
            ShipmentStatus.AWAITING_PICKUP,
            ShipmentStatus.PICKED_UP,
            ShipmentStatus.CANCELLED,
        }
    ),
    ShipmentStatus.PICKED_UP: frozenset(),
    ShipmentStatus.CANCELLED: frozenset(),
}


# ============================================================
# SHIPMENT MODEL
# ============================================================


class Shipment(MerchantOwnedModel):
    """
    Merchant-owned shipment awaiting courier pickup.

    A shipment can only enter PICKED_UP status after
    verified pickup evidence is recorded.
    """

    __tablename__ = "shipments"

    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "tracking_number",
            name="uq_shipments_merchant_tracking",
        ),
        UniqueConstraint(
            "id",
            "merchant_id",
            name="uq_shipments_id_merchant",
        ),
        ForeignKeyConstraint(
            ["courier_company_id", "merchant_id"],
            [
                "courier_companies.id",
                "courier_companies.merchant_id",
            ],
            name="fk_shipments_company_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["courier_agent_id", "merchant_id"],
            [
                "courier_agents.id",
                "courier_agents.merchant_id",
            ],
            name="fk_shipments_agent_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "pickup_window_end IS NULL "
            "OR pickup_window_start IS NULL "
            "OR pickup_window_end >= pickup_window_start",
            name="pickup_window_valid",
        ),
        CheckConstraint(
            "status != 'picked_up' "
            "OR (pickup_scanned_at IS NOT NULL "
            "AND pickup_evidence_type IS NOT NULL "
            "AND pickup_evidence_reference IS NOT NULL)",
            name="pickup_requires_evidence",
        ),
        Index(
            "ix_shipments_merchant_status",
            "merchant_id",
            "status",
        ),
        Index(
            "ix_shipments_merchant_pickup_deadline",
            "merchant_id",
            "pickup_window_end",
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

    # --------------------------------------------------------
    # Shipment identifiers
    # --------------------------------------------------------

    tracking_number: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    external_order_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    external_shipment_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    # --------------------------------------------------------
    # Courier assignments
    # --------------------------------------------------------

    courier_company_id: Mapped[str | None] = mapped_column(
        UUIDString(),
        nullable=True,
    )

    courier_agent_id: Mapped[str | None] = mapped_column(
        UUIDString(),
        nullable=True,
    )

    # --------------------------------------------------------
    # Status and priority
    # --------------------------------------------------------

    status: Mapped[ShipmentStatus] = mapped_column(
        SAEnum(
            ShipmentStatus,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=ShipmentStatus.CREATED,
    )

    priority: Mapped[ShipmentPriority] = mapped_column(
        SAEnum(
            ShipmentPriority,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=ShipmentPriority.NORMAL,
    )

    # --------------------------------------------------------
    # Pickup scheduling
    # --------------------------------------------------------

    pickup_window_start: Mapped[datetime | None] = mapped_column(nullable=True)

    pickup_window_end: Mapped[datetime | None] = mapped_column(nullable=True)

    pickup_requested_at: Mapped[datetime | None] = mapped_column(nullable=True)

    pickup_exception_detected_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # --------------------------------------------------------
    # Pickup evidence
    # --------------------------------------------------------

    pickup_scanned_at: Mapped[datetime | None] = mapped_column(nullable=True)

    pickup_evidence_type: Mapped[PickupEvidenceType | None] = mapped_column(
        SAEnum(
            PickupEvidenceType,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=True,
    )

    pickup_evidence_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    pickup_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # --------------------------------------------------------
    # Operational metadata
    # --------------------------------------------------------

    pickup_location_code: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    # --------------------------------------------------------
    # Status transitions
    # --------------------------------------------------------

    def can_transition_to(
        self,
        new_status: ShipmentStatus,
    ) -> bool:
        current = self.status or ShipmentStatus.CREATED

        return new_status in ALLOWED_TRANSITIONS[current]

    def transition_to(
        self,
        new_status: ShipmentStatus,
    ) -> None:
        current = self.status or ShipmentStatus.CREATED

        if not self.can_transition_to(new_status):
            raise ValueError(f"Invalid shipment transition: {current.value} -> {new_status.value}")

        if new_status == ShipmentStatus.PICKED_UP and not self.has_pickup_evidence:
            raise ValueError("Verified pickup evidence is required.")

        self.status = new_status

        if new_status == ShipmentStatus.PICKUP_EXCEPTION:
            self.pickup_exception_detected_at = utc_now()

    # --------------------------------------------------------
    # Pickup scheduling
    # --------------------------------------------------------

    def schedule_pickup(
        self,
        start: datetime,
        end: datetime,
    ) -> None:
        start_utc = ensure_utc(start)
        end_utc = ensure_utc(end)

        if end_utc < start_utc:
            raise ValueError("Pickup window end must not precede start.")

        if self.status != ShipmentStatus.CREATED:
            raise ValueError("Only new shipments can be scheduled.")

        self.pickup_window_start = start_utc
        self.pickup_window_end = end_utc
        self.pickup_requested_at = utc_now()

        self.transition_to(ShipmentStatus.SCHEDULED)

    # --------------------------------------------------------
    # Evidence-based pickup completion
    # --------------------------------------------------------

    @property
    def has_pickup_evidence(self) -> bool:
        return all(
            (
                self.pickup_scanned_at is not None,
                self.pickup_verified_at is not None,
                self.pickup_evidence_type is not None,
                bool(self.pickup_evidence_reference),
            )
        )

    def record_verified_pickup(
        self,
        *,
        scanned_at: datetime,
        evidence_type: PickupEvidenceType,
        evidence_reference: str,
    ) -> None:
        """
        Record already-verified pickup evidence.

        This method does NOT independently authenticate
        provider scans or webhooks. The service layer must
        validate the evidence source before calling it.
        """

        if self.status in {
            ShipmentStatus.PICKED_UP,
            ShipmentStatus.CANCELLED,
        }:
            raise ValueError("Terminal shipments cannot be modified.")

        reference = evidence_reference.strip()

        if not reference:
            raise ValueError("Pickup evidence reference is required.")

        if not isinstance(evidence_type, PickupEvidenceType):
            raise ValueError("Invalid pickup evidence type.")

        scan_time = ensure_utc(scanned_at)

        if scan_time > utc_now():
            raise ValueError("Pickup scan cannot be in the future.")

        self.pickup_scanned_at = scan_time
        self.pickup_evidence_type = evidence_type
        self.pickup_evidence_reference = reference
        self.pickup_verified_at = utc_now()

        self.transition_to(ShipmentStatus.PICKED_UP)

    # --------------------------------------------------------
    # Exception detection
    # --------------------------------------------------------

    def is_pickup_overdue(
        self,
        *,
        now: datetime | None = None,
        grace_minutes: int = 0,
    ) -> bool:
        """
        Determine whether the pickup deadline has passed.

        Detection alone does not create an exception case.
        That will be implemented in the exception service.
        """
        from datetime import timedelta

        if grace_minutes < 0:
            raise ValueError("Grace period cannot be negative.")

        if self.status not in {
            ShipmentStatus.SCHEDULED,
            ShipmentStatus.AWAITING_PICKUP,
        }:
            return False

        if self.pickup_window_end is None:
            return False

        current = ensure_utc(now or utc_now())

        deadline = ensure_utc(self.pickup_window_end) + timedelta(minutes=grace_minutes)

        return current > deadline

    # --------------------------------------------------------
    # Safe public representation
    # --------------------------------------------------------

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "merchant_id": self.merchant_id,
            "tracking_number": self.tracking_number,
            "status": (self.status.value if self.status is not None else None),
            "priority": (self.priority.value if self.priority is not None else None),
            "courier_company_id": self.courier_company_id,
            "courier_agent_id": self.courier_agent_id,
            "has_pickup_evidence": self.has_pickup_evidence,
            "is_demo": self.is_demo,
        }

    def __repr__(self) -> str:
        return (
            f"Shipment(id={self.id!r}, "
            f"tracking_number={self.tracking_number!r}, "
            f"status={self.status!r})"
        )


__all__ = [
    "Shipment",
    "ShipmentStatus",
    "ShipmentPriority",
    "PickupEvidenceType",
    "ALLOWED_TRANSITIONS",
]
