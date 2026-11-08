"""Development-only pickup exception detection API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.shipments import (
    get_db,
    get_demo_merchant,
    require_dev_mode,
)
from app.services.exception_detection import (
    detect_overdue_pickups,
)

router = APIRouter(
    prefix="/api/v1/detection",
    tags=["Detection"],
    dependencies=[Depends(require_dev_mode)],
)

DBSession = Annotated[Session, Depends(get_db)]


class DetectionRequest(BaseModel):
    limit: int = Field(default=500, ge=1, le=5000)


class DetectionResponse(BaseModel):
    scanned: int
    overdue: int
    created: int
    skipped_existing: int


@router.post(
    "/scan",
    response_model=DetectionResponse,
)
def scan_overdue_pickups(
    payload: DetectionRequest,
    db: DBSession,
):
    merchant = get_demo_merchant(db)

    try:
        result = detect_overdue_pickups(
            db,
            merchant_id=merchant.id,
            limit=payload.limit,
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    return DetectionResponse(
        scanned=result.scanned,
        overdue=result.overdue,
        created=result.created,
        skipped_existing=result.skipped_existing,
    )
