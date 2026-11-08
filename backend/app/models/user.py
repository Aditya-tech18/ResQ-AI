"""
DispatchResolve AI — Merchant User Model.

Stores:
- Merchant-linked user identity
- Argon2 password hashes
- Role assignments
- Account lifecycle state
- Email verification metadata
- Failed login counters and lockout timestamps
- Last successful login timestamp
- Password change timestamp

Security:
- Passwords are never stored in plaintext.
- Authentication metadata is not exposed publicly.
- Cross-merchant authorization must be enforced in services.
- Database account state must be checked during authentication.
- Sensitive operations require audit events.
"""

from __future__ import annotations

import enum
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime

from app.core.security import (
    Role,
    hash_password,
    verify_password,
)
from app.db.base import (
    MerchantOwnedModel,
    ensure_utc,
    utc_now,
)

# ============================================================
# ACCOUNT STATUS
# ============================================================


class UserStatus(enum.StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


# ============================================================
# VALIDATION HELPERS
# ============================================================

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def normalize_email(value: str) -> str:
    """
    Normalize an email address for application-level use.

    More comprehensive email validation will be performed
    in Pydantic request schemas.
    """
    normalized = value.strip().lower()

    if len(normalized) > 254 or not EMAIL_PATTERN.fullmatch(normalized):
        raise ValueError("Invalid email address.")

    return normalized


# ============================================================
# USER DATABASE MODEL
# ============================================================


class User(MerchantOwnedModel):
    """
    A user belongs to exactly one merchant.

    Each merchant can have its own users and role
    assignments.

    The same email may belong to different merchants,
    but must be unique within a merchant.
    """

    __tablename__ = "users"

    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "email",
            name="uq_users_merchant_email",
        ),
        CheckConstraint(
            "failed_login_attempts >= 0",
            name="failed_login_nonnegative",
        ),
        Index(
            "ix_users_merchant_status",
            "merchant_id",
            "status",
        ),
    )

    # --------------------------------------------------------
    # Merchant relationship
    # --------------------------------------------------------

    merchant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "merchants.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    merchant: Mapped[Any] = relationship(
        "Merchant",
        lazy="raise",
    )

    # --------------------------------------------------------
    # Identity
    # --------------------------------------------------------

    email: Mapped[str] = mapped_column(
        String(254),
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

    # --------------------------------------------------------
    # Authentication
    # --------------------------------------------------------

    password_hash: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )

    role: Mapped[Role] = mapped_column(
        SAEnum(
            Role,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=Role.VIEWER,
    )

    status: Mapped[UserStatus] = mapped_column(
        SAEnum(
            UserStatus,
            native_enum=False,
            values_callable=lambda values: [item.value for item in values],
            length=32,
        ),
        nullable=False,
        default=UserStatus.INVITED,
    )

    # --------------------------------------------------------
    # Email verification
    # --------------------------------------------------------

    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # Login security metadata
    # --------------------------------------------------------

    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    invited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # Password methods
    # --------------------------------------------------------

    def set_password(self, password: str) -> None:
        """
        Hash and store a password.

        Never save or log the plaintext password.
        """
        self.password_hash = hash_password(password)
        self.password_changed_at = utc_now()

    def check_password(self, password: str) -> bool:
        """
        Verify a password.

        This method only checks the hash. Login services
        must separately enforce account status, lockouts,
        rate limits and merchant eligibility.
        """
        return verify_password(
            password,
            self.password_hash,
        )

    # --------------------------------------------------------
    # Account lifecycle
    # --------------------------------------------------------

    def activate(self) -> None:
        if self.status == UserStatus.DISABLED:
            raise ValueError("Disabled accounts require administrative review.")

        self.status = UserStatus.ACTIVE

    def suspend(self) -> None:
        if self.status == UserStatus.DISABLED:
            raise ValueError("Disabled accounts cannot be suspended.")

        self.status = UserStatus.SUSPENDED

    def disable(self) -> None:
        self.status = UserStatus.DISABLED
        self.disabled_at = utc_now()

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    # --------------------------------------------------------
    # Email verification
    # --------------------------------------------------------

    def mark_email_verified(self) -> None:
        self.email_verified = True
        self.email_verified_at = utc_now()

    # --------------------------------------------------------
    # Login attempt tracking
    # --------------------------------------------------------

    def is_locked(self, now: datetime | None = None) -> bool:
        if self.locked_until is None:
            return False

        current = ensure_utc(now or utc_now())

        return current < ensure_utc(self.locked_until)

    def record_failed_login(
        self,
        now: datetime | None = None,
    ) -> None:
        current = ensure_utc(now or utc_now())

        if self.is_locked(current):
            return

        self.failed_login_attempts = (self.failed_login_attempts or 0) + 1

        if self.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
            self.locked_until = current + timedelta(minutes=LOCKOUT_MINUTES)
            self.failed_login_attempts = 0

    def record_successful_login(
        self,
        now: datetime | None = None,
    ) -> None:
        current = ensure_utc(now or utc_now())

        if self.status != UserStatus.ACTIVE:
            raise ValueError("Inactive accounts cannot log in.")

        if self.is_locked(current):
            raise ValueError("Account is temporarily locked.")

        self.failed_login_attempts = 0
        self.locked_until = None
        self.last_login_at = current

    # --------------------------------------------------------
    # Safe representation
    # --------------------------------------------------------

    def to_public_dict(self) -> dict[str, Any]:
        """
        Explicit public serialization.

        Password hashes, login counters, lockout data,
        and verification internals are excluded.
        """
        return {
            "id": self.id,
            "merchant_id": self.merchant_id,
            "full_name": self.full_name,
            "role": (self.role.value if self.role is not None else None),
            "status": (self.status.value if self.status is not None else None),
            "is_active": self.is_active,
        }

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, role={self.role!r}, status={self.status!r})"


__all__ = [
    "User",
    "UserStatus",
    "normalize_email",
    "MAX_FAILED_LOGIN_ATTEMPTS",
    "LOCKOUT_MINUTES",
]
