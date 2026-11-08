"""Detect overdue courier pickups and create exception cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import ensure_utc, utc_now
from app.models.exception_case import (
    ExceptionCase,
    ExceptionCaseStatus,
    ExceptionReason,
    ExceptionSeverity,
)
from app.models.shipment import Shipment, ShipmentStatus


@dataclass
class DetectionResult:
    scanned: int = 0
    overdue: int = 0
    created: int = 0
    skipped_existing: int = 0


CLOSED_STATUSES = {
    ExceptionCaseStatus.RESOLVED,
    ExceptionCaseStatus.CANCELLED,
}


def detect_overdue_pickups(
    db: Session,
    *,
    merchant_id: str,
    now: datetime | None = None,
    limit: int = 500,
) -> DetectionResult:
    """
    Scan a single merchant's shipments.

    Caller is responsible for:
    - authenticating the merchant
    - transaction commit/rollback
    - scheduling periodic scans

    This service does not send notifications.
    """

    if not merchant_id:
        raise ValueError("Merchant ID is required.")

    if not 1 <= limit <= 5000:
        raise ValueError("Limit must be between 1 and 5000.")

    current = ensure_utc(now or utc_now())
    result = DetectionResult()

    # PostgreSQL supports row-level locking. SQLite
    # development mode serializes writers at the DB level.
    bind = db.get_bind()
    dialect = bind.dialect.name

    query = (
        select(Shipment)
        .where(
            Shipment.merchant_id == merchant_id,
            Shipment.status.in_(
                [
                    ShipmentStatus.SCHEDULED,
                    ShipmentStatus.AWAITING_PICKUP,
                ]
            ),
        )
        .order_by(Shipment.created_at.asc())
        .limit(limit)
    )

    if dialect == "postgresql":
        query = query.with_for_update(skip_locked=True)

    # PostgreSQL supports row-level locking. SQLite
    # development mode serializes writers at the DB level.
    bind = db.get_bind()
    dialect = bind.dialect.name

    query = (
        select(Shipment)
        .where(
            Shipment.merchant_id == merchant_id,
            Shipment.status.in_(
                [
                    ShipmentStatus.SCHEDULED,
                    ShipmentStatus.AWAITING_PICKUP,
                ]
            ),
        )
        .order_by(Shipment.created_at.asc())
        .limit(limit)
    )

    if dialect == "postgresql":
        query = query.with_for_update(skip_locked=True)

    shipments = db.scalars(query).all()

    for shipment in shipments:
        result.scanned += 1

        if not shipment.is_pickup_overdue(now=current):
            continue

        result.overdue += 1

        existing = db.scalar(
            select(ExceptionCase).where(
                ExceptionCase.merchant_id == merchant_id,
                ExceptionCase.shipment_id == shipment.id,
                ExceptionCase.status.notin_(CLOSED_STATUSES),
            )
        )

        if existing is not None:
            result.skipped_existing += 1
            continue

        case = ExceptionCase(
            merchant_id=merchant_id,
            shipment_id=shipment.id,
            case_number=("AUTO-" + uuid4().hex[:16].upper()),
            summary=("Scheduled courier pickup was not completed before the deadline."),
            reason=ExceptionReason.COURIER_NO_SHOW,
            severity=ExceptionSeverity.HIGH,
        )

        db.add(case)
        db.flush()

        result.created += 1

    return result


__all__ = [
    "DetectionResult",
    "detect_overdue_pickups",
]
