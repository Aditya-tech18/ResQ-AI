"""Local development shipment API.

IMPORTANT: This router is not production-authenticated.
It is enabled only when DISPATCH_DEV_API=1.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.commitment import Commitment  # noqa: F401
from app.models.courier import CourierAgent, CourierCompany  # noqa: F401
from app.models.escalation import Escalation  # noqa: F401
from app.models.exception_case import ExceptionCase  # noqa: F401
from app.models.merchant import Merchant
from app.models.shipment import Shipment
from app.models.shipment_event import ShipmentEvent  # noqa: F401
from app.models.user import User  # noqa: F401

router = APIRouter(
    prefix="/api/v1/shipments",
    tags=["Shipments"],
)

DB_PATH = Path("data/dispatchresolve_dev.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH.resolve()}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def enable_foreign_keys(dbapi_connection, _):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    expire_on_commit=False,
)

if os.getenv("DISPATCH_DEV_API") == "1":
    Base.metadata.create_all(engine)


def get_db():
    with SessionLocal() as session:
        yield session


class ShipmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tracking_number: str = Field(min_length=1, max_length=100)


class ShipmentResponse(BaseModel):
    id: str
    tracking_number: str
    merchant_id: str
    status: str


def require_dev_mode():
    if os.getenv("DISPATCH_DEV_API") != "1":
        raise HTTPException(
            status_code=404,
            detail="Not found",
        )


def get_demo_merchant(db: Session) -> Merchant:
    merchant = db.scalar(select(Merchant).where(Merchant.code == "LOCAL_DEMO"))

    if merchant is None:
        merchant = Merchant(
            code="LOCAL_DEMO",
            name="Local Demo Merchant",
        )
        db.add(merchant)
        db.flush()

    return merchant


def serialize(shipment: Shipment) -> ShipmentResponse:
    return ShipmentResponse(
        id=str(shipment.id),
        tracking_number=shipment.tracking_number,
        merchant_id=str(shipment.merchant_id),
        status=shipment.status.value,
    )


@router.post(
    "",
    response_model=ShipmentResponse,
    status_code=201,
    dependencies=[Depends(require_dev_mode)],
)
def create_shipment(
    payload: ShipmentCreate,
    db: Annotated[Session, Depends(get_db)],
):
    merchant = get_demo_merchant(db)

    tracking = payload.tracking_number.strip()

    if not tracking:
        raise HTTPException(
            status_code=422,
            detail="Tracking number cannot be blank",
        )

    existing = db.scalar(
        select(Shipment).where(
            Shipment.merchant_id == merchant.id,
            Shipment.tracking_number == tracking,
        )
    )

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Tracking number already exists",
        )

    shipment = Shipment(
        merchant_id=merchant.id,
        tracking_number=tracking,
        is_demo=True,
    )

    db.add(shipment)
    db.commit()
    db.refresh(shipment)

    return serialize(shipment)


@router.get(
    "",
    response_model=list[ShipmentResponse],
    dependencies=[Depends(require_dev_mode)],
)
def list_shipments(
    db: Annotated[Session, Depends(get_db)],
):
    merchant = get_demo_merchant(db)

    shipments = db.scalars(
        select(Shipment)
        .where(Shipment.merchant_id == merchant.id)
        .order_by(Shipment.created_at.desc())
        .limit(100)
    ).all()

    return [serialize(item) for item in shipments]


@router.get(
    "/{shipment_id}",
    response_model=ShipmentResponse,
    dependencies=[Depends(require_dev_mode)],
)
def get_shipment(
    shipment_id: UUID,
    db: Annotated[Session, Depends(get_db)],
):
    merchant = get_demo_merchant(db)

    shipment = db.scalar(
        select(Shipment).where(
            Shipment.id == str(shipment_id),
            Shipment.merchant_id == merchant.id,
        )
    )

    if shipment is None:
        raise HTTPException(
            status_code=404,
            detail="Shipment not found",
        )

    return serialize(shipment)
