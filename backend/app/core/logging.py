"""
DispatchResolve AI — Secure Structured Logging.

Features:
- Structured JSON logs for production.
- Human-readable logs for local development.
- Request correlation IDs using contextvars.
- Recursive sensitive-field redaction.
- Token and credential masking in text messages.
- Safe exception logging.
- Idempotent logger configuration.
- Standard-library-only implementation.

Security note:
Logging is not a substitute for data classification.
Never deliberately log raw audio, customer PII, API keys,
authentication headers, or full third-party responses.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

SERVICE_NAME = "dispatchresolve-api"

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "dispatchresolve_request_id",
    default=None,
)

REDACTED = "[REDACTED]"

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "secret_key",
        "jwt_secret_key",
        "access_token",
        "refresh_token",
        "id_token",
        "api_key",
        "gnani_api_key",
        "gnani_stt_api_key",
        "gnani_tts_api_key",
        "ai_api_key",
        "authorization",
        "proxy_authorization",
        "cookie",
        "set_cookie",
        "client_secret",
        "private_key",
        "database_url",
        "connection_string",
        "phone",
        "phone_number",
        "mobile",
        "email",
        "email_address",
        "customer_address",
        "delivery_address",
        "transcript",
        "raw_transcript",
        "audio_data",
        "audio_bytes",
        "audio_base64",
    }
)

SECRET_PATTERNS = (
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/-]+"),
    re.compile(r"(?i)\b(basic)\s+[A-Za-z0-9+/=]+"),
    re.compile(
        r"(?i)\b("
        r"api[_-]?key|"
        r"access[_-]?token|"
        r"refresh[_-]?token|"
        r"password|"
        r"client[_-]?secret"
        r")\s*[:=]\s*[^\s,;&]+"
    ),
)


def normalize_key(key: object) -> str:
    """Normalize field names for sensitive-field matching."""
    return re.sub(
        r"[^a-z0-9]+",
        "_",
        str(key).lower(),
    ).strip("_")


def is_sensitive_key(key: object) -> bool:
    """Check whether a field is classified as sensitive."""
    normalized = normalize_key(key)

    if normalized in SENSITIVE_KEYS:
        return True

    suffixes = (
        "_password",
        "_secret",
        "_token",
        "_api_key",
        "_authorization",
        "_private_key",
    )

    return normalized.endswith(suffixes)


def redact_text(value: str) -> str:
    """
    Mask common credential patterns in text.

    This is defense in depth, not guaranteed detection
    of arbitrary secret strings or personal information.
    """
    sanitized = value

    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub(
            lambda match: (
                match.group(1) + " " + REDACTED
                if match.group(1).lower()
                in {
                    "bearer",
                    "basic",
                }
                else match.group(1) + "=" + REDACTED
            ),
            sanitized,
        )

    return sanitized


def sanitize(
    value: Any,
    *,
    depth: int = 0,
    max_depth: int = 6,
) -> Any:
    """
    Recursively sanitize structured log data.

    Restrict recursion depth and collection sizes to
    reduce the risk of excessive logging or cyclic data.
    """
    if depth >= max_depth:
        return "[MAX_DEPTH]"

    if value is None or isinstance(
        value,
        (bool, int, float),
    ):
        return value

    if isinstance(value, str):
        return redact_text(value[:4000])

    if isinstance(value, bytes):
        return f"[BINARY_DATA:{len(value)}_BYTES]"

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}

        for index, (key, item) in enumerate(value.items()):
            if index >= 100:
                result["_truncated"] = True
                break

            safe_key = str(key)[:100]

            result[safe_key] = (
                REDACTED
                if is_sensitive_key(key)
                else sanitize(
                    item,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            )

        return result

    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        sanitized = [
            sanitize(
                item,
                depth=depth + 1,
                max_depth=max_depth,
            )
            for item in items[:100]
        ]

        if len(items) > 100:
            sanitized.append("[TRUNCATED]")

        return sanitized

    return f"[UNSUPPORTED_TYPE:{type(value).__name__}]"


def new_request_id() -> str:
    """Create a random, non-identifying correlation ID."""
    return uuid.uuid4().hex


def set_request_id(
    request_id: str | None = None,
) -> contextvars.Token[str | None]:
    """Bind a request ID to the current execution context."""
    candidate = request_id or new_request_id()

    if not re.fullmatch(
        r"[A-Za-z0-9_-]{1,64}",
        candidate,
    ):
        candidate = new_request_id()

    return _request_id.set(candidate)


def get_request_id() -> str | None:
    """Return the request ID for the current context."""
    return _request_id.get()


def reset_request_id(
    token: contextvars.Token[str | None],
) -> None:
    """Restore the previous request context."""
    _request_id.reset(token)


class RequestContextFilter(logging.Filter):
    """Attach request correlation metadata to log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        record.service = SERVICE_NAME
        return True


class SecureJSONFormatter(logging.Formatter):
    """Render log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(
            record.created,
            tz=UTC,
        ).isoformat()

        payload: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "service": SERVICE_NAME,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
            "request_id": getattr(
                record,
                "request_id",
                None,
            ),
        }

        if record.exc_info:
            exc_type = record.exc_info[0]
            payload["exception_type"] = (
                exc_type.__name__ if exc_type is not None else "UnknownException"
            )
            payload["exception_details"] = "Exception captured; details omitted"

        return json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        )


class SecureConsoleFormatter(logging.Formatter):
    """Readable local logs without raw exception traces."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(
            record.created,
            tz=UTC,
        ).strftime("%H:%M:%S")

        request_id = getattr(
            record,
            "request_id",
            None,
        )

        correlation = f" [{request_id[:12]}]" if request_id else ""

        message = redact_text(record.getMessage())

        if record.exc_info:
            message += " [exception captured]"

        return f"{timestamp} {record.levelname:<8} {record.name}{correlation} {message}"


def configure_logging(
    level: str = "INFO",
    *,
    json_output: bool = False,
) -> None:
    """
    Configure application logging safely.

    Removes only handlers previously installed by this
    function. Does not replace unrelated logging handlers.
    """
    normalized_level = level.upper()

    if normalized_level not in {
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    }:
        raise ValueError(f"Unsupported log level: {level}")

    root = logging.getLogger()

    for handler in root.handlers[:]:
        if getattr(
            handler,
            "_dispatchresolve_managed",
            False,
        ):
            root.removeHandler(handler)
            handler.close()

    handler = logging.StreamHandler(sys.stdout)

    handler._dispatchresolve_managed = True

    handler.addFilter(RequestContextFilter())

    handler.setFormatter(SecureJSONFormatter() if json_output else SecureConsoleFormatter())

    root.addHandler(handler)
    root.setLevel(getattr(logging, normalized_level))

    # Reduce accidental exposure from noisy libraries.
    for name in (
        "httpx",
        "httpcore",
        "urllib3",
        "sqlalchemy.engine",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a standard named application logger."""
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: Literal[
        "debug",
        "info",
        "warning",
        "error",
        "critical",
    ] = "info",
    **fields: Any,
) -> None:
    """
    Log a structured business event.

    The event name must be static and controlled by
    application code, not directly by user input.
    """
    if not re.fullmatch(
        r"[a-z][a-z0-9_.-]{0,99}",
        event,
    ):
        raise ValueError("Invalid event name")

    safe_fields = sanitize(fields)

    logger.log(
        getattr(logging, level.upper()),
        "%s %s",
        event,
        json.dumps(
            safe_fields,
            ensure_ascii=False,
            default=str,
        ),
    )


__all__ = [
    "REDACTED",
    "RequestContextFilter",
    "SecureJSONFormatter",
    "SecureConsoleFormatter",
    "configure_logging",
    "get_logger",
    "get_request_id",
    "is_sensitive_key",
    "log_event",
    "new_request_id",
    "normalize_key",
    "redact_text",
    "reset_request_id",
    "sanitize",
    "set_request_id",
]
