"""Multilingual rescue decision API."""

from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.rescue_decision_service import RescueDecisionService

router = APIRouter(
    prefix="/api/v1/rescue-ai",
    tags=["Rescue AI"],
)


class RescueDecisionRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    speaker_role: Literal[
        "driver",
        "replacement_driver",
        "customer",
        "dispatcher",
    ] = "replacement_driver"


@lru_cache(maxsize=1)
def get_service() -> RescueDecisionService:
    return RescueDecisionService()


@router.post("/evaluate")
def evaluate_rescue(payload: RescueDecisionRequest):
    try:
        return get_service().evaluate(
            message=payload.message,
            speaker_role=payload.speaker_role,
        )
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="AI evaluation temporarily unavailable.",
        ) from None
