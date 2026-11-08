"""
DispatchResolve AI — Merchant database model.

A merchant is a business using DispatchResolve AI.
Each merchant can own users, shipments and exception cases.
"""

from __future__ import annotations

import enum
import re
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.db.base import UUIDTimestampModel, utc_now


class MerchantStatus(enum.StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class SubscriptionPlan(enum.StrEnum):
    FREE = "free"
    STARTER = "starter"
    GROWTH = "growth"
    ENTERPRISE = "enterprise"


class MerchantIndustry(enum.StrEnum):
    FASHION = "fashion"
    ELECTRONICS = "electronics"
    BEAUTY = "beauty"
    FOOD = "food"
    HOME = "home"
    HEALTHCARE = "healthcare"
    GENERAL = "general"
    OTHER = "other"


MERCHANT_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,31}$")


def normalize_merchant_code(value: str) -> str:
    normalized = value.strip().upper().replace("-", "_").replace(" ", "_")

    if not MERCHANT_CODE_PATTERN.fullmatch(normalized):
        raise ValueError("Invalid merchant code.")

    return normalized


def default_merchant_settings() -> dict[str, Any]:
    return {
        "pickup": {
            "grace_period_minutes": 30,
            "commitment_reminder_minutes": 15,
            "auto_escalation_enabled": True,
            "require_pickup_scan_for_closure": True,
        },
        "voice": {
            "enabled": True,
            "default_language": "hi-IN",
            "allow_hinglish": True,
        },
        "notifications": {
            "email_enabled": False,
            "whatsapp_enabled": False,
        },
        "demo": {
            "synthetic_data_enabled": False,
        },
    }


class Merchant(UUIDTimestampModel):
    __tablename__ = "merchants"

    __table_args__ = (
        CheckConstraint(
            "pickup_grace_minutes >= 0 AND pickup_grace_minutes <= 1440",
            name="pickup_grace_valid",
        ),
        CheckConstraint(
            "commitment_reminder_minutes >= 0 AND commitment_reminder_minutes <= 1440",
            name="commitment_reminder_valid",
        ),
        Index(
            "ix_merchants_status_plan",
            "status",
            "subscription_plan",
        ),
    )

    code: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    legal_name: Mapped[str | None] = mapped_column(
        String(250),
        nullable=True,
    )

    industry: Mapped[MerchantIndustry] = mapped_column(
        SAEnum(
            MerchantIndustry,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=MerchantIndustry.GENERAL,
    )

    contact_email: Mapped[str | None] = mapped_column(
        String(254),
        nullable=True,
    )

    contact_phone: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    website_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    status: Mapped[MerchantStatus] = mapped_column(
        SAEnum(
            MerchantStatus,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=MerchantStatus.PENDING,
        index=True,
    )

    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    subscription_plan: Mapped[SubscriptionPlan] = mapped_column(
        SAEnum(
            SubscriptionPlan,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=SubscriptionPlan.FREE,
    )

    subscription_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    country_code: Mapped[str] = mapped_column(
        String(2),
        nullable=False,
        default="IN",
    )

    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="Asia/Kolkata",
    )

    currency_code: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="INR",
    )

    pickup_grace_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
    )

    commitment_reminder_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=15,
    )

    auto_escalation_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    require_pickup_scan_for_closure: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    settings_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=default_merchant_settings,
    )

    internal_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    def activate(self) -> None:
        if self.status == MerchantStatus.CLOSED:
            raise ValueError("A closed merchant cannot be reactivated.")

        self.status = MerchantStatus.ACTIVE
        self.activated_at = utc_now()
        self.suspended_at = None

    def suspend(self) -> None:
        if self.status == MerchantStatus.CLOSED:
            raise ValueError("A closed merchant cannot be suspended.")

        self.status = MerchantStatus.SUSPENDED
        self.suspended_at = utc_now()

    def close(self) -> None:
        self.status = MerchantStatus.CLOSED
        self.closed_at = utc_now()

    @property
    def is_active(self) -> bool:
        return self.status == MerchantStatus.ACTIVE

    @property
    def is_closed(self) -> bool:
        return self.status == MerchantStatus.CLOSED

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "industry": (self.industry.value if self.industry is not None else None),
            "status": (self.status.value if self.status is not None else None),
            "subscription_plan": (
                self.subscription_plan.value if self.subscription_plan is not None else None
            ),
            "country_code": self.country_code,
            "timezone": self.timezone,
            "currency_code": self.currency_code,
            "is_active": self.is_active,
        }

    def __repr__(self) -> str:
        return f"Merchant(id={self.id!r}, code={self.code!r}, status={self.status!r})"


__all__ = [
    "Merchant",
    "MerchantStatus",
    "SubscriptionPlan",
    "MerchantIndustry",
    "normalize_merchant_code",
    "default_merchant_settings",
]
