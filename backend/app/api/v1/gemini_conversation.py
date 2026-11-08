"""Multilingual AI conversation endpoints for local demo testing."""

from functools import lru_cache

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.gemini_multilingual_engine import (
    ConversationResult,
    GeminiMultilingualEngine,
)

router = APIRouter(
    prefix="/gemini",
    tags=["Gemini Multilingual AI"],
)


class ConversationRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    speaker_role: str = "driver"
    conversation_history: list[dict[str, str]] = Field(
        default_factory=list,
        max_length=12,
    )


@lru_cache(maxsize=1)
def get_engine():
    return GeminiMultilingualEngine()


@router.post("/analyze", response_model=ConversationResult)
def analyze(payload: ConversationRequest):
    allowed_roles = {
        "driver",
        "replacement_driver",
        "customer",
        "dispatcher",
    }

    if payload.speaker_role not in allowed_roles:
        raise HTTPException(
            status_code=422,
            detail="Invalid speaker role",
        )

    try:
        return get_engine().analyze(
            payload.message,
            speaker_role=payload.speaker_role,
            conversation_history=payload.conversation_history,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="AI processing failed",
        ) from exc
