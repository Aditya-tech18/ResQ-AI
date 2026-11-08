"""
DispatchResolve AI — Authentication and Authorization.

Security capabilities:
- Argon2 password hashing and verification
- Signed JWT access and refresh tokens
- Strict JWT claim and token-type validation
- Role-based access control
- Permission-based authorization
- FastAPI-compatible security dependencies
- Secret-safe authentication failures

Important:
- JWTs are signed, not encrypted.
- Never place passwords or personal data in JWT payloads.
- Refresh-token rotation and revocation require persistent
  session storage, implemented in later modules.
- Authentication endpoints must implement rate limiting.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any

import jwt
from fastapi import Depends
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
)

# ============================================================
# PASSWORD HASHING
# ============================================================

_password_hasher = PasswordHash.recommended()

MAX_PASSWORD_BYTES = 1024


def hash_password(
    password: str,
    *,
    settings: Settings | None = None,
) -> str:
    """
    Hash a password using Argon2.

    Enforce application password length requirements.
    """
    config = settings or get_settings()

    if len(password) < config.PASSWORD_MIN_LENGTH:
        raise ValueError("Password does not meet minimum length.")

    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("Password exceeds maximum supported size.")

    return _password_hasher.hash(password)


def verify_password(
    password: str,
    password_hash: str,
) -> bool:
    """Verify a plaintext password against its stored hash."""
    try:
        return _password_hasher.verify(
            password,
            password_hash,
        )
    except (ValueError, TypeError):
        return False


def password_needs_rehash(
    password_hash: str,
) -> bool:
    """Check whether stored hash parameters need upgrading."""
    return _password_hasher.check_needs_rehash(password_hash)


# ============================================================
# ROLES AND PERMISSIONS
# ============================================================


class Role(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    MERCHANT_ADMIN = "merchant_admin"
    OPERATIONS_MANAGER = "operations_manager"
    DISPATCHER = "dispatcher"
    ANALYST = "analyst"
    VIEWER = "viewer"


class Permission(StrEnum):
    SHIPMENT_READ = "shipment:read"
    SHIPMENT_WRITE = "shipment:write"

    CASE_READ = "case:read"
    CASE_WRITE = "case:write"
    CASE_CLOSE = "case:close"

    VOICE_USE = "voice:use"

    ESCALATION_READ = "escalation:read"
    ESCALATION_WRITE = "escalation:write"

    ANALYTICS_READ = "analytics:read"

    USER_MANAGE = "user:manage"
    SETTINGS_MANAGE = "settings:manage"

    AUDIT_READ = "audit:read"


ALL_PERMISSIONS = frozenset(Permission)


ROLE_PERMISSIONS: dict[
    Role,
    frozenset[Permission],
] = {
    Role.PLATFORM_ADMIN: ALL_PERMISSIONS,
    Role.MERCHANT_ADMIN: ALL_PERMISSIONS,
    Role.OPERATIONS_MANAGER: frozenset(
        {
            Permission.SHIPMENT_READ,
            Permission.SHIPMENT_WRITE,
            Permission.CASE_READ,
            Permission.CASE_WRITE,
            Permission.CASE_CLOSE,
            Permission.VOICE_USE,
            Permission.ESCALATION_READ,
            Permission.ESCALATION_WRITE,
            Permission.ANALYTICS_READ,
            Permission.AUDIT_READ,
        }
    ),
    Role.DISPATCHER: frozenset(
        {
            Permission.SHIPMENT_READ,
            Permission.CASE_READ,
            Permission.CASE_WRITE,
            Permission.VOICE_USE,
            Permission.ESCALATION_READ,
            Permission.ESCALATION_WRITE,
        }
    ),
    Role.ANALYST: frozenset(
        {
            Permission.SHIPMENT_READ,
            Permission.CASE_READ,
            Permission.ESCALATION_READ,
            Permission.ANALYTICS_READ,
        }
    ),
    Role.VIEWER: frozenset(
        {
            Permission.SHIPMENT_READ,
            Permission.CASE_READ,
            Permission.ESCALATION_READ,
        }
    ),
}


def has_permission(
    role: Role,
    permission: Permission,
) -> bool:
    """Return whether a role grants a given permission."""
    return permission in ROLE_PERMISSIONS.get(
        role,
        frozenset(),
    )


# ============================================================
# TOKEN DATA
# ============================================================


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    user_id: str
    merchant_id: str
    role: Role
    token_id: str
    issued_at: datetime
    expires_at: datetime


JWT_ISSUER = "dispatchresolve-ai"
JWT_AUDIENCE = "dispatchresolve-api"

JWT_ALLOWED_ALGORITHMS = (
    "HS256",
    "HS384",
    "HS512",
)


def _jwt_secret(settings: Settings) -> str:
    """
    Retrieve configured signing key.

    Do not silently create random signing keys on startup:
    doing so would invalidate tokens after each restart.
    """
    if settings.JWT_SECRET_KEY is None:
        raise RuntimeError("JWT_SECRET_KEY is not configured.")

    secret = settings.JWT_SECRET_KEY.get_secret_value()

    if len(secret.encode("utf-8")) < 32:
        raise RuntimeError("JWT signing secret must be at least 32 bytes.")

    return secret


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _create_token(
    *,
    user_id: str,
    merchant_id: str,
    role: Role,
    token_type: str,
    lifetime: timedelta,
    settings: Settings,
) -> str:
    if not user_id or not merchant_id:
        raise ValueError("User and merchant identifiers are required.")

    now = _utc_now()

    claims: dict[str, Any] = {
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "sub": user_id,
        "merchant_id": merchant_id,
        "role": role.value,
        "type": token_type,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "nbf": now,
        "exp": now + lifetime,
    }

    return jwt.encode(
        claims,
        _jwt_secret(settings),
        algorithm=settings.JWT_ALGORITHM,
    )


def create_access_token(
    *,
    user_id: str,
    merchant_id: str,
    role: Role,
    settings: Settings | None = None,
) -> str:
    """Issue a short-lived access token."""
    config = settings or get_settings()

    return _create_token(
        user_id=user_id,
        merchant_id=merchant_id,
        role=role,
        token_type="access",  # noqa: S106
        lifetime=timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES),
        settings=config,
    )


def create_refresh_token(
    *,
    user_id: str,
    merchant_id: str,
    role: Role,
    settings: Settings | None = None,
) -> str:
    """Issue a refresh token requiring server-side tracking."""
    config = settings or get_settings()

    return _create_token(
        user_id=user_id,
        merchant_id=merchant_id,
        role=role,
        token_type="refresh",  # noqa: S106
        lifetime=timedelta(days=config.REFRESH_TOKEN_EXPIRE_DAYS),
        settings=config,
    )


def decode_token(
    token: str,
    *,
    expected_type: str = "access",
    settings: Settings | None = None,
) -> AuthenticatedPrincipal:
    """
    Verify JWT signature, expiry, issuer, audience,
    required claims and token type.
    """
    config = settings or get_settings()

    if expected_type not in {"access", "refresh"}:
        raise ValueError("Unsupported expected token type.")

    try:
        claims = jwt.decode(
            token,
            _jwt_secret(config),
            algorithms=[config.JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
            options={
                "require": [
                    "exp",
                    "iat",
                    "nbf",
                    "iss",
                    "aud",
                    "sub",
                    "jti",
                    "type",
                    "merchant_id",
                    "role",
                ],
                "verify_signature": True,
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iat": True,
            },
            leeway=5,
        )

        if claims.get("type") != expected_type:
            raise AuthenticationError("Invalid authentication token.")

        role = Role(claims["role"])

        user_id = claims["sub"]
        merchant_id = claims["merchant_id"]
        token_id = claims["jti"]

        if not all(
            isinstance(value, str) and value
            for value in (
                user_id,
                merchant_id,
                token_id,
            )
        ):
            raise AuthenticationError("Invalid authentication token.")

        return AuthenticatedPrincipal(
            user_id=user_id,
            merchant_id=merchant_id,
            role=role,
            token_id=token_id,
            issued_at=datetime.fromtimestamp(
                claims["iat"],
                tz=UTC,
            ),
            expires_at=datetime.fromtimestamp(
                claims["exp"],
                tz=UTC,
            ),
        )

    except (
        InvalidTokenError,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        raise AuthenticationError("Invalid or expired authentication token.") from exc


# ============================================================
# FASTAPI AUTHENTICATION DEPENDENCIES
# ============================================================

_bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="DispatchResolveBearer",
)


async def get_current_principal(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ],
) -> AuthenticatedPrincipal:
    """Validate the bearer token from an incoming request."""

    if credentials is None:
        raise AuthenticationError()

    if credentials.scheme.lower() != "bearer":
        raise AuthenticationError()

    if not credentials.credentials:
        raise AuthenticationError()

    return decode_token(
        credentials.credentials,
        expected_type="access",
    )


def require_permission(
    permission: Permission,
) -> Any:
    """
    Create a reusable FastAPI permission dependency.

    Example:
        Depends(require_permission(Permission.CASE_CLOSE))
    """

    async def permission_dependency(
        principal: Annotated[
            AuthenticatedPrincipal,
            Depends(get_current_principal),
        ],
    ) -> AuthenticatedPrincipal:

        if not has_permission(
            principal.role,
            permission,
        ):
            raise AuthorizationError()

        return principal

    return permission_dependency


def require_role(
    *allowed_roles: Role,
) -> Any:
    """Require membership in one of the specified roles."""

    if not allowed_roles:
        raise ValueError("At least one allowed role is required.")

    async def role_dependency(
        principal: Annotated[
            AuthenticatedPrincipal,
            Depends(get_current_principal),
        ],
    ) -> AuthenticatedPrincipal:

        if principal.role not in allowed_roles:
            raise AuthorizationError()

        return principal

    return role_dependency


# ============================================================
# SECURE RANDOM VALUES
# ============================================================


def generate_secure_token(
    nbytes: int = 32,
) -> str:
    """Generate a cryptographically secure random token."""

    if not 16 <= nbytes <= 128:
        raise ValueError("Token size must be between 16 and 128 bytes.")

    return secrets.token_urlsafe(nbytes)


__all__ = [
    "Role",
    "Permission",
    "AuthenticatedPrincipal",
    "ROLE_PERMISSIONS",
    "hash_password",
    "verify_password",
    "password_needs_rehash",
    "has_permission",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "get_current_principal",
    "require_permission",
    "require_role",
    "generate_secure_token",
]
