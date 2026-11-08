"""Development authentication endpoints.

Production activation requires authenticated tenant-scoped
database sessions and security integration tests.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.shipments import get_db, require_dev_mode
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
)
from app.models.user import User, UserStatus

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Authentication"],
    dependencies=[Depends(require_dev_mode)],
)

DBSession = Annotated[Session, Depends(get_db)]


class LoginRequest(BaseModel):
    email: str = Field(
        min_length=3,
        max_length=254,
    )
    password: str = Field(
        min_length=1,
        max_length=1024,
    )


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105


@router.post(
    "/login",
    response_model=TokenResponse,
)
def login(
    payload: LoginRequest,
    db: DBSession,
) -> TokenResponse:
    email = payload.email.strip().lower()

    if not email or "@" not in email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid email format",
        )

    user = db.scalar(
        select(User).where(
            func.lower(User.email) == email,
        )
    )

    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if user is None:
        raise invalid_credentials

    if user.status != UserStatus.ACTIVE:
        raise invalid_credentials

    if not verify_password(
        payload.password,
        user.password_hash,
    ):
        raise invalid_credentials

    return TokenResponse(
        access_token=create_access_token(
            user_id=str(user.id),
            merchant_id=str(user.merchant_id),
            role=user.role,
        ),
        refresh_token=create_refresh_token(
            user_id=str(user.id),
            merchant_id=str(user.merchant_id),
            role=user.role,
        ),
    )
