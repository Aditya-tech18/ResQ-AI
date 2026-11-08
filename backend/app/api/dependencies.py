"""Authentication and merchant isolation dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.shipments import get_db
from app.core.security import (
    AuthenticatedPrincipal,
    get_current_principal,
)
from app.models.user import User, UserStatus

DBSession = Annotated[Session, Depends(get_db)]

Principal = Annotated[
    AuthenticatedPrincipal,
    Depends(get_current_principal),
]


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    merchant_id: str
    role: str


def get_auth_context(
    principal: Principal,
    db: DBSession,
) -> AuthContext:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user = db.get(User, str(principal.user_id))

    if user is None:
        raise unauthorized

    if user.status != UserStatus.ACTIVE:
        raise unauthorized

    if str(user.merchant_id) != str(principal.merchant_id):
        raise unauthorized

    if user.role != principal.role:
        raise unauthorized

    return AuthContext(
        user_id=str(user.id),
        merchant_id=str(user.merchant_id),
        role=str(user.role.value),
    )


CurrentAuth = Annotated[
    AuthContext,
    Depends(get_auth_context),
]
