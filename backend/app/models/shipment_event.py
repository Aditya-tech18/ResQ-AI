"""
DispatchResolve AI — Shipment Event History.

Append-only operational event records.

Examples:
- Pickup scheduled
- Courier no-show detected
- Courier contacted
- Pickup commitment recorded
- Commitment missed
- Case escalated
- Pickup scan verified

Security:
- Merchant-scoped foreign keys
- Unique event idempotency keys
- Actor attribution
- No silent updates or deletions through ORM
- Raw secrets and audio are not stored

Production services must also enforce:
- Actor authorization
- Source authentication
- Transactional event creation
- Retention and privacy policies
- Database-level append-only permissions
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    event,
    inspect,
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


class ShipmentEventType(enum.StrEnum):
    SHIPMENT_CREATED = "shipment_created"
    PICKUP_SCHEDULED = "pickup_scheduled"
    PICKUP_OVERDUE = "pickup_overdue"
    PICKUP_EXCEPTION_DETECTED = "pickup_exception_detected"
    COURIER_ASSIGNED = "courier_assigned"
    COURIER_CONTACTED = "courier_contacted"
    VOICE_TRANSCRIBED = "voice_transcribed"
    REASON_CLASSIFIED = "reason_classified"
    COMMITMENT_RECORDED = "commitment_recorded"
    COMMITMENT_MISSED = "commitment_missed"
    CASE_ASSIGNED = "case_assigned"
    CASE_ESCALATED = "case_escalated"
    REMINDER_SCHEDULED = "reminder_scheduled"
    REMINDER_SENT = "reminder_sent"
    PICKUP_SCAN_RECEIVED = "pickup_scan_received"
    PICKUP_VERIFIED = "pickup_verified"
    CASE_RESOLVED = "case_resolved"
    SHIPMENT_CANCELLED = "shipment_cancelled"
    SYSTEM_NOTE = "system_note"


class EventActorType(enum.StrEnum):
    SYSTEM = "system"
    MERCHANT_USER = "merchant_user"
    COURIER_AGENT = "courier_agent"
    PROVIDER_WEBHOOK = "provider_webhook"
    AI_SERVICE = "ai_service"
    DEMO_SIMULATOR = "demo_simulator"


class EventSource(enum.StrEnum):
    INTERNAL = "internal"
    DISPATCHER = "dispatcher"
    COURIER_API = "courier_api"
    WEBHOOK = "webhook"
    GNANI_STT = "gnani_stt"
    AUTOMATION = "automation"
    DEMO = "demo"


class ShipmentEvent(MerchantOwnedModel):
    """
    Immutable operational timeline event.

    This model is intentionally append-only.

    Its inherited updated_at and version_id fields
    remain unchanged after initial creation.
    """

    __tablename__ = "shipment_events"

    __table_args__ = (
        ForeignKeyConstraint(
            ["shipment_id", "merchant_id"],
            ["shipments.id", "shipments.merchant_id"],
            name="fk_shipment_events_shipment_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "merchant_id",
            "idempotency_key",
            name="uq_shipment_events_idempotency",
        ),
        Index(
            "ix_shipment_events_timeline",
            "merchant_id",
            "shipment_id",
            "occurred_at",
        ),
        Index(
            "ix_shipment_events_type",
            "merchant_id",
            "event_type",
        ),
        Index(
            "ix_shipment_events_correlation",
            "correlation_id",
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

    event_type: Mapped[ShipmentEventType] = mapped_column(
        SAEnum(
            ShipmentEventType,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=64,
        ),
        nullable=False,
    )

    actor_type: Mapped[EventActorType] = mapped_column(
        SAEnum(
            EventActorType,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
    )

    actor_id: Mapped[str | None] = mapped_column(
        UUIDString(),
        nullable=True,
    )

    source: Mapped[EventSource] = mapped_column(
        SAEnum(
            EventSource,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=EventSource.INTERNAL,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=utc_now,
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(180),
        nullable=False,
    )

    correlation_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    source_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    summary: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )

    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    @classmethod
    def create(
        cls,
        *,
        merchant_id: str,
        shipment_id: str,
        event_type: ShipmentEventType,
        actor_type: EventActorType,
        idempotency_key: str,
        summary: str,
        source: EventSource = EventSource.INTERNAL,
        actor_id: str | None = None,
        correlation_id: str | None = None,
        source_reference: str | None = None,
        occurred_at: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ShipmentEvent:
        """
        Construct a new event.

        Authorization and idempotent retry handling
        belong to the event service.
        """

        if not idempotency_key.strip():
            raise ValueError("Idempotency key is required.")

        if not summary.strip():
            raise ValueError("Event summary is required.")

        if len(idempotency_key) > 180:
            raise ValueError("Idempotency key is too long.")

        if len(summary) > 300:
            raise ValueError("Event summary is too long.")

        return cls(
            merchant_id=merchant_id,
            shipment_id=shipment_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            source=source,
            occurred_at=ensure_utc(occurred_at or utc_now()),
            idempotency_key=idempotency_key.strip(),
            correlation_id=correlation_id,
            source_reference=source_reference,
            summary=summary.strip(),
            payload_json=dict(payload or {}),
        )

    def to_public_dict(self) -> dict[str, Any]:
        """
        Safe timeline representation.

        Internal payload and source reference are
        deliberately excluded.
        """

        return {
            "id": self.id,
            "merchant_id": self.merchant_id,
            "shipment_id": self.shipment_id,
            "event_type": self.event_type.value,
            "actor_type": self.actor_type.value,
            "source": self.source.value,
            "occurred_at": (self.occurred_at.isoformat() if self.occurred_at else None),
            "summary": self.summary,
        }

    def __repr__(self) -> str:
        return f"ShipmentEvent(id={self.id!r}, type={self.event_type!r})"


@event.listens_for(ShipmentEvent, "before_update")
def prevent_event_update(
    mapper: Any,
    connection: Any,
    target: ShipmentEvent,
) -> None:
    """
    Reject ORM updates to persisted events.

    Direct SQL bypasses this hook and requires
    database-level permissions in production.
    """
    if inspect(target).persistent:
        raise ValueError("Shipment events are append-only.")


@event.listens_for(ShipmentEvent, "before_delete")
def prevent_event_delete(
    mapper: Any,
    connection: Any,
    target: ShipmentEvent,
) -> None:
    raise ValueError("Shipment events cannot be deleted.")


__all__ = [
    "ShipmentEvent",
    "ShipmentEventType",
    "EventActorType",
    "EventSource",
]
