"""
DispatchResolve AI — SQLAlchemy Database Model Foundation.

Provides:
- SQLAlchemy 2.0 DeclarativeBase
- Predictable database constraint naming
- Portable UUID primary keys
- UTC-aware application timestamps
- Created/updated timestamp mixins
- Optimistic concurrency versioning
- Tenant identifier mixin
- Reusable database model foundations

This module defines models and conventions only.
Database engines and sessions are configured separately.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Integer,
    MetaData,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
)
from sqlalchemy.types import CHAR, TypeDecorator

# ============================================================
# DATABASE NAMING CONVENTIONS
# ============================================================

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": ("fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"),
    "pk": "pk_%(table_name)s",
}


metadata = MetaData(naming_convention=NAMING_CONVENTION)


# ============================================================
# UTC TIME HELPERS
# ============================================================


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """
    Normalize datetime values to UTC.

    Naive datetime values are treated as UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value.astimezone(UTC)


# ============================================================
# PORTABLE UUID COLUMN TYPE
# ============================================================


class UUIDString(TypeDecorator[str]):
    """
    Store UUIDs consistently as 36-character strings.

    Compatible with SQLite and PostgreSQL.
    Can later be migrated to native PostgreSQL UUID
    if database-specific optimization is required.
    """

    impl = CHAR(36)
    cache_ok = True

    def process_bind_param(
        self,
        value: str | uuid.UUID | None,
        dialect: Any,
    ) -> str | None:
        if value is None:
            return None

        try:
            return str(uuid.UUID(str(value)))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("Invalid UUID value.") from exc

    def process_result_value(
        self,
        value: str | None,
        dialect: Any,
    ) -> str | None:
        return value


def generate_uuid() -> str:
    """Generate a random UUID v4 string."""
    return str(uuid.uuid4())


# ============================================================
# BASE DECLARATIVE CLASS
# ============================================================


class Base(DeclarativeBase):
    """
    Shared declarative base for every database model.

    SQLAlchemy collects mapped models under Base.metadata.
    """

    metadata = metadata

    type_annotation_map = {
        uuid.UUID: UUIDString(),
    }

    def to_safe_dict(
        self,
        *fields: str,
    ) -> dict[str, Any]:
        """
        Serialize only explicitly allowlisted model fields.

        This intentionally avoids automatic serialization
        of passwords, secrets, personal data and relationships.
        """
        if not fields:
            raise ValueError("Explicit field names are required.")

        result: dict[str, Any] = {}

        for field in fields:
            if field.startswith("_"):
                raise ValueError("Private fields cannot be serialized.")

            mapper = self.__mapper__

            if field not in mapper.column_attrs:
                raise ValueError(f"Unsupported model field: {field}")

            value = getattr(self, field)

            if isinstance(value, datetime):
                value = ensure_utc(value).isoformat()

            elif isinstance(value, uuid.UUID):
                value = str(value)

            result[field] = value

        return result


# ============================================================
# UUID PRIMARY KEY MIXIN
# ============================================================


class UUIDPrimaryKeyMixin:
    """
    Reusable UUID primary key.

    Example:
        class Shipment(UUIDPrimaryKeyMixin, Base):
            __tablename__ = "shipments"
    """

    id: Mapped[str] = mapped_column(
        UUIDString(),
        primary_key=True,
        default=generate_uuid,
        nullable=False,
    )


# ============================================================
# CREATED / UPDATED TIMESTAMP MIXIN
# ============================================================


class TimestampMixin:
    """
    Automatic created_at and updated_at timestamps.

    Values are generated in UTC by Python.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


# ============================================================
# TENANT / MERCHANT ISOLATION MIXIN
# ============================================================


class MerchantScopedMixin:
    """
    Add merchant_id to tenant-owned records.

    Important:
    This column does not automatically enforce tenant
    isolation. Every query and mutation must be scoped
    to the authenticated merchant in the service layer.

    PostgreSQL Row-Level Security can provide an
    additional defense-in-depth layer later.
    """

    @declared_attr
    def merchant_id(cls) -> Mapped[str]:
        return mapped_column(
            UUIDString(),
            nullable=False,
            index=True,
        )


# ============================================================
# OPTIMISTIC CONCURRENCY CONTROL
# ============================================================


class VersionedMixin:
    """
    Prevent silent overwrites of concurrently edited rows.

    SQLAlchemy checks version_id during UPDATE/DELETE.
    If another transaction changed the row first,
    a StaleDataError is raised.

    Example:
        class Shipment(VersionedMixin, Base):
            ...
    """

    version_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {
            "version_id_col": cls.version_id,
        }


# ============================================================
# OPTIONAL SOFT DELETE MIXIN
# ============================================================


class SoftDeleteMixin:
    """
    Support logical deletion where legally appropriate.

    Deleted records must be explicitly excluded from
    ordinary queries by repository/service logic.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        self.deleted_at = utc_now()

    def restore(self) -> None:
        self.deleted_at = None


# ============================================================
# COMMON MODEL BUILDING BLOCKS
# ============================================================


class UUIDTimestampModel(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    """
    Abstract base for UUID + timestamp models.

    Example:
        class Courier(UUIDTimestampModel):
            __tablename__ = "couriers"
    """

    __abstract__ = True


class MerchantOwnedModel(
    UUIDPrimaryKeyMixin,
    MerchantScopedMixin,
    TimestampMixin,
    VersionedMixin,
    Base,
):
    """
    Abstract base for merchant-owned operational records.

    Suitable for shipments, exception cases, courier
    commitments and escalations.
    """

    __abstract__ = True


# ============================================================
# DATABASE MODEL REGISTRY HELPERS
# ============================================================


def get_registered_tables() -> list[str]:
    """Return sorted names of registered SQLAlchemy tables."""
    return sorted(Base.metadata.tables.keys())


def get_model_metadata() -> MetaData:
    """Expose the shared metadata for Alembic migrations."""
    return Base.metadata


__all__ = [
    "Base",
    "NAMING_CONVENTION",
    "UUIDString",
    "UUIDPrimaryKeyMixin",
    "TimestampMixin",
    "MerchantScopedMixin",
    "VersionedMixin",
    "SoftDeleteMixin",
    "UUIDTimestampModel",
    "MerchantOwnedModel",
    "generate_uuid",
    "utc_now",
    "ensure_utc",
    "get_registered_tables",
    "get_model_metadata",
]
