"""Authenticated current-user endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.dependencies import CurrentAuth

router = APIRouter(
    prefix="/api/v1",
    tags=["Authentication"],
)


class CurrentUserResponse(BaseModel):
    user_id: str
    merchant_id: str
    role: str


@router.get(
    "/auth/me",
    response_model=CurrentUserResponse,
)
def get_me(auth: CurrentAuth) -> CurrentUserResponse:
    return CurrentUserResponse(
        user_id=auth.user_id,
        merchant_id=auth.merchant_id,
        role=auth.role,
    )
