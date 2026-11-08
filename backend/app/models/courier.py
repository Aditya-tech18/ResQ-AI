"""
DispatchResolve AI — Courier Companies and Pickup Agents.

Models:
- CourierCompany: logistics provider accessible to a merchant
- CourierAgent: pickup agent working with that provider

Features:
- Merchant ownership
- Unique provider codes per merchant
- Agent identity and contact metadata
- Availability and account lifecycle
- Optional external provider identifiers
- Pickup assignment capacity
- Operational preferences

Reliability scores are intentionally not stored here.
They will be computed from verified pickup events.
"""

from __future__ import annotations

import enum
import re
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    MerchantOwnedModel,
    UUIDString,
    utc_now,
)

# ============================================================
# ENUMERATIONS
# ============================================================


class CourierCompanyStatus(enum.StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class CourierAgentStatus(enum.StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class AgentAvailability(enum.StrEnum):
    AVAILABLE = "available"
    BUSY = "busy"
    OFF_DUTY = "off_duty"
    UNKNOWN = "unknown"


class CourierServiceType(enum.StrEnum):
    STANDARD = "standard"
    EXPRESS = "express"
    SAME_DAY = "same_day"
    HYPERLOCAL = "hyperlocal"
    OTHER = "other"


# ============================================================
# VALIDATION HELPERS
# ============================================================

COURIER_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,39}$")


def normalize_courier_code(value: str) -> str:
    """
    Example:
        'delhivery-express' -> 'DELHIVERY_EXPRESS'
    """
    result = value.strip().upper().replace("-", "_").replace(" ", "_")

    if not COURIER_CODE_PATTERN.fullmatch(result):
        raise ValueError(
            "Courier code must be 3-40 characters, "
            "start with a letter, and contain only "
            "letters, digits or underscores."
        )

    return result


# ============================================================
# COURIER COMPANY
# ============================================================


class CourierCompany(MerchantOwnedModel):
    """
    Merchant-specific courier provider configuration.

    The same physical courier company may appear under
    multiple merchants as separate operational records.
    """

    __tablename__ = "courier_companies"

    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "code",
            name="uq_courier_companies_merchant_code",
        ),
        UniqueConstraint(
            "id",
            "merchant_id",
            name="uq_courier_companies_id_merchant",
        ),
        Index(
            "ix_courier_companies_merchant_status",
            "merchant_id",
            "status",
        ),
    )

    merchant_id: Mapped[str] = mapped_column(
        UUIDString(),
        ForeignKey(
            "merchants.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    service_type: Mapped[CourierServiceType] = mapped_column(
        SAEnum(
            CourierServiceType,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=CourierServiceType.STANDARD,
    )

    status: Mapped[CourierCompanyStatus] = mapped_column(
        SAEnum(
            CourierCompanyStatus,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=CourierCompanyStatus.ACTIVE,
    )

    external_provider_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    support_email: Mapped[str | None] = mapped_column(
        String(254),
        nullable=True,
    )

    support_phone: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    tracking_url_template: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    is_pickup_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    agents: Mapped[list[CourierAgent]] = relationship(
        "CourierAgent",
        back_populates="company",
        lazy="raise",
    )

    @property
    def is_active(self) -> bool:
        return self.status == CourierCompanyStatus.ACTIVE

    def suspend(self) -> None:
        self.status = CourierCompanyStatus.SUSPENDED

    def activate(self) -> None:
        self.status = CourierCompanyStatus.ACTIVE

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "merchant_id": self.merchant_id,
            "code": self.code,
            "name": self.name,
            "service_type": (self.service_type.value if self.service_type is not None else None),
            "status": (self.status.value if self.status is not None else None),
            "is_active": self.is_active,
        }

    def __repr__(self) -> str:
        return f"CourierCompany(id={self.id!r}, code={self.code!r})"


# ============================================================
# COURIER AGENT
# ============================================================


class CourierAgent(MerchantOwnedModel):
    """
    Pickup agent assigned to a merchant's courier company.

    Agent contact details are operational PII and must
    only be exposed to authorized merchant users.
    """

    __tablename__ = "courier_agents"

    __table_args__ = (
        UniqueConstraint(
            "id",
            "merchant_id",
            name="uq_courier_agents_id_merchant",
        ),
        ForeignKeyConstraint(
            ["company_id", "merchant_id"],
            ["courier_companies.id", "courier_companies.merchant_id"],
            name="fk_courier_agents_company_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "merchant_id",
            "company_id",
            "agent_code",
            name="uq_courier_agents_company_code",
        ),
        CheckConstraint(
            "max_daily_pickups >= 0 AND max_daily_pickups <= 10000",
            name="max_daily_pickups_valid",
        ),
        Index(
            "ix_courier_agents_merchant_company",
            "merchant_id",
            "company_id",
        ),
        Index(
            "ix_courier_agents_merchant_availability",
            "merchant_id",
            "availability",
        ),
    )

    merchant_id: Mapped[str] = mapped_column(
        UUIDString(),
        ForeignKey(
            "merchants.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    company_id: Mapped[str] = mapped_column(
        UUIDString(),
        nullable=False,
    )

    agent_code: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
    )

    full_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    phone_number: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    alternate_phone: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    preferred_language: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="hi-IN",
    )

    service_area: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    status: Mapped[CourierAgentStatus] = mapped_column(
        SAEnum(
            CourierAgentStatus,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=CourierAgentStatus.ACTIVE,
    )

    availability: Mapped[AgentAvailability] = mapped_column(
        SAEnum(
            AgentAvailability,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=AgentAvailability.UNKNOWN,
    )

    max_daily_pickups: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=50,
    )

    last_assigned_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    last_seen_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    company: Mapped[CourierCompany] = relationship(
        "CourierCompany",
        back_populates="agents",
        primaryjoin=(
            "and_("
            "CourierAgent.company_id == CourierCompany.id, "
            "CourierAgent.merchant_id == "
            "CourierCompany.merchant_id)"
        ),
        foreign_keys="[CourierAgent.company_id]",
        lazy="raise",
    )

    def mark_available(self) -> None:
        if self.status != CourierAgentStatus.ACTIVE:
            raise ValueError("Inactive agents cannot become available.")

        self.availability = AgentAvailability.AVAILABLE
        self.last_seen_at = utc_now()

    def mark_busy(self) -> None:
        if self.status != CourierAgentStatus.ACTIVE:
            raise ValueError("Inactive agents cannot become busy.")

        self.availability = AgentAvailability.BUSY
        self.last_seen_at = utc_now()

    def mark_off_duty(self) -> None:
        self.availability = AgentAvailability.OFF_DUTY
        self.last_seen_at = utc_now()

    def suspend(self) -> None:
        self.status = CourierAgentStatus.SUSPENDED
        self.availability = AgentAvailability.OFF_DUTY

    @property
    def can_accept_pickup(self) -> bool:
        return (
            self.status == CourierAgentStatus.ACTIVE
            and self.availability == AgentAvailability.AVAILABLE
            and self.max_daily_pickups > 0
        )

    def to_public_dict(self) -> dict[str, Any]:
        """
        Safe operational summary.

        Contact phone numbers are intentionally excluded.
        """
        return {
            "id": self.id,
            "merchant_id": self.merchant_id,
            "company_id": self.company_id,
            "agent_code": self.agent_code,
            "full_name": self.full_name,
            "status": (self.status.value if self.status is not None else None),
            "availability": (self.availability.value if self.availability is not None else None),
            "can_accept_pickup": self.can_accept_pickup,
        }

    def __repr__(self) -> str:
        return f"CourierAgent(id={self.id!r}, agent_code={self.agent_code!r})"


__all__ = [
    "CourierCompany",
    "CourierAgent",
    "CourierCompanyStatus",
    "CourierAgentStatus",
    "AgentAvailability",
    "CourierServiceType",
    "normalize_courier_code",
]
