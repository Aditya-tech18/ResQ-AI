"""Development-only exception case API."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.shipments import (
    get_db,
    get_demo_merchant,
    require_dev_mode,
)
from app.models.exception_case import (
    ExceptionCase,
    ExceptionReason,
    ExceptionSeverity,
)
from app.models.shipment import Shipment

router = APIRouter(
    prefix="/api/v1/exceptions",
    tags=["Exceptions"],
    dependencies=[Depends(require_dev_mode)],
)

DBSession = Annotated[Session, Depends(get_db)]


class ExceptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipment_id: UUID
    summary: str = Field(min_length=1, max_length=300)
    reason: ExceptionReason = ExceptionReason.COURIER_NO_SHOW
    severity: ExceptionSeverity = ExceptionSeverity.HIGH


class ExceptionResponse(BaseModel):
    id: str
    merchant_id: str
    shipment_id: str
    case_number: str
    summary: str
    reason: str
    severity: str
    status: str


def enum_value(value):
    return value.value if hasattr(value, "value") else str(value)


def serialize(case: ExceptionCase) -> ExceptionResponse:
    return ExceptionResponse(
        id=str(case.id),
        merchant_id=str(case.merchant_id),
        shipment_id=str(case.shipment_id),
        case_number=case.case_number,
        summary=case.summary,
        reason=enum_value(case.reason),
        severity=enum_value(case.severity),
        status=enum_value(case.status),
    )


@router.post(
    "",
    response_model=ExceptionResponse,
    status_code=201,
)
def create_exception(
    payload: ExceptionCreate,
    db: DBSession,
):
    merchant = get_demo_merchant(db)

    shipment = db.scalar(
        select(Shipment).where(
            Shipment.id == str(payload.shipment_id),
            Shipment.merchant_id == merchant.id,
        )
    )

    if shipment is None:
        raise HTTPException(
            status_code=404,
            detail="Shipment not found",
        )

    summary = payload.summary.strip()

    if not summary:
        raise HTTPException(
            status_code=422,
            detail="Summary cannot be blank",
        )

    case = ExceptionCase(
        merchant_id=merchant.id,
        shipment_id=shipment.id,
        case_number=f"EXC-{uuid4().hex[:12].upper()}",
        summary=summary,
        reason=payload.reason,
        severity=payload.severity,
    )

    db.add(case)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Could not create exception",
        ) from None

    db.refresh(case)
    return serialize(case)


@router.get(
    "",
    response_model=list[ExceptionResponse],
)
def list_exceptions(db: DBSession):
    merchant = get_demo_merchant(db)

    cases = db.scalars(
        select(ExceptionCase)
        .where(ExceptionCase.merchant_id == merchant.id)
        .order_by(ExceptionCase.created_at.desc())
        .limit(100)
    ).all()

    return [serialize(case) for case in cases]


@router.get(
    "/{case_id}",
    response_model=ExceptionResponse,
)
def get_exception(
    case_id: UUID,
    db: DBSession,
):
    merchant = get_demo_merchant(db)

    case = db.scalar(
        select(ExceptionCase).where(
            ExceptionCase.id == str(case_id),
            ExceptionCase.merchant_id == merchant.id,
        )
    )

    if case is None:
        raise HTTPException(
            status_code=404,
            detail="Exception not found",
        )

    return serialize(case)
