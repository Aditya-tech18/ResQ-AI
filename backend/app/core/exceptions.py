"""
DispatchResolve AI — Domain exceptions and safe API errors.

Public errors must not expose passwords, tokens, stack traces,
database details or third-party provider responses.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as HTTPExceptionBase

from app.core.logging import get_logger, get_request_id

logger = get_logger(__name__)


class DispatchResolveError(Exception):
    status_code = 500
    error_code = "APPLICATION_ERROR"
    public_message = "The request could not be completed."

    def __init__(self) -> None:
        super().__init__(self.public_message)


class BadRequestError(DispatchResolveError):
    status_code = 400
    error_code = "BAD_REQUEST"
    public_message = "Invalid request."


class ResourceNotFoundError(DispatchResolveError):
    status_code = 404
    error_code = "RESOURCE_NOT_FOUND"
    public_message = "Resource not found."


class ConflictError(DispatchResolveError):
    status_code = 409
    error_code = "CONFLICT"
    public_message = "The operation conflicts with existing state."


class AuthenticationError(DispatchResolveError):
    status_code = 401
    error_code = "AUTHENTICATION_REQUIRED"
    public_message = "Invalid or missing authentication credentials."

    def __init__(self, message: str | None = None) -> None:
        # Intentionally do not expose caller-supplied messages.
        super().__init__()


class AuthorizationError(DispatchResolveError):
    status_code = 403
    error_code = "ACCESS_DENIED"
    public_message = "You do not have permission to perform this action."


class BusinessRuleViolationError(ConflictError):
    error_code = "BUSINESS_RULE_VIOLATION"
    public_message = "This operation violates a business rule."


class ShipmentNotFoundError(ResourceNotFoundError):
    error_code = "SHIPMENT_NOT_FOUND"
    public_message = "Shipment not found."


class ExceptionCaseNotFoundError(ResourceNotFoundError):
    error_code = "EXCEPTION_CASE_NOT_FOUND"
    public_message = "Exception case not found."


class PickupEvidenceRequiredError(BusinessRuleViolationError):
    error_code = "PICKUP_EVIDENCE_REQUIRED"
    public_message = "Verified pickup evidence is required for closure."


class InvalidShipmentTransitionError(BusinessRuleViolationError):
    error_code = "INVALID_SHIPMENT_TRANSITION"
    public_message = "Invalid shipment status transition."


class DuplicateShipmentEventError(ConflictError):
    error_code = "DUPLICATE_SHIPMENT_EVENT"
    public_message = "Shipment event has already been processed."


class ExternalServiceError(DispatchResolveError):
    status_code = 502
    error_code = "EXTERNAL_SERVICE_ERROR"
    public_message = "An external service could not complete the request."


class GnaniServiceError(ExternalServiceError):
    error_code = "GNANI_SERVICE_ERROR"
    public_message = "Voice AI service could not complete the request."


class GnaniTimeoutError(ExternalServiceError):
    status_code = 504
    error_code = "GNANI_TIMEOUT"
    public_message = "Voice AI service timed out."


class GnaniConfigurationError(ExternalServiceError):
    status_code = 503
    error_code = "GNANI_NOT_CONFIGURED"
    public_message = "Voice AI is not configured."


def error_response(
    code: str,
    message: str,
    status_code: int,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "request_id": get_request_id(),
            },
        },
    )


async def application_error_handler(
    request: Request,
    exc: DispatchResolveError,
) -> JSONResponse:
    logger.warning(
        "Application error: code=%s status=%s",
        exc.error_code,
        exc.status_code,
    )
    return error_response(
        exc.error_code,
        exc.public_message,
        exc.status_code,
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    # Do not return rejected values, ctx, or raw validation errors.
    return error_response(
        "VALIDATION_ERROR",
        "Request validation failed.",
        422,
    )


async def http_error_handler(
    request: Request,
    exc: HTTPExceptionBase,
) -> JSONResponse:
    messages = {
        401: "Authentication required.",
        403: "Access denied.",
        404: "Resource not found.",
        405: "Method not allowed.",
        429: "Too many requests.",
    }
    response = error_response(
        f"HTTP_{exc.status_code}",
        messages.get(exc.status_code, "Request failed."),
        exc.status_code,
    )
    if exc.headers:
        for key, value in exc.headers.items():
            if key.lower() in {"www-authenticate", "allow", "retry-after"}:
                response.headers[key] = value
    return response


async def unexpected_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.error(
        "Unexpected error type=%s",
        type(exc).__name__,
    )
    return error_response(
        "INTERNAL_SERVER_ERROR",
        "An unexpected server error occurred.",
        500,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        DispatchResolveError,
        application_error_handler,
    )
    app.add_exception_handler(
        RequestValidationError,
        validation_error_handler,
    )
    app.add_exception_handler(
        HTTPExceptionBase,
        http_error_handler,
    )
    app.add_exception_handler(
        Exception,
        unexpected_error_handler,
    )
