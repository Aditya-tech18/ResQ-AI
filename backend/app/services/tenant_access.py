"""Merchant-scoped database access helpers."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import AuthContext
from app.models.exception_case import ExceptionCase
from app.models.shipment import Shipment


def get_merchant_record[T: (Shipment, ExceptionCase)](
    db: Session,
    model: type[T],
    record_id: str,
    auth: AuthContext,
) -> T:
    """Fetch a record only within the authenticated merchant."""

    record = db.scalar(
        select(model).where(
            model.id == record_id,
            model.merchant_id == auth.merchant_id,
        )
    )

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )

    return record


def list_merchant_records[T: (Shipment, ExceptionCase)](
    db: Session,
    model: type[T],
    auth: AuthContext,
    limit: int = 100,
) -> list[T]:
    """List records belonging to the authenticated merchant."""

    if not 1 <= limit <= 500:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Limit must be between 1 and 500",
        )

    statement = select(model).where(model.merchant_id == auth.merchant_id).limit(limit)

    return list(db.scalars(statement).all())
