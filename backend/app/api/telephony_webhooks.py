"""HTTP endpoint for authenticated telephony webhook ingestion.

This router is provider-neutral. It uses the application's own
HMAC protocol, not a confirmed Gnani webhook signature scheme.

Security:
- The raw HTTP body is verified before parsing into business data.
- The signing secret is never returned to clients.
- Successful responses require durable database persistence.
- No webhook event directly approves a rescue assignment.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from app.services.telephony_webhook_ingestion import (
    TelephonyWebhookIngestionService,
    WebhookIngestionError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/telephony",
    tags=["Telephony Webhooks"],
)


class WebhookAcknowledgment(BaseModel):
    """Safe response returned to the webhook sender."""

    accepted: bool
    event_id: str
    status: str


@router.post(
    "/webhooks",
    response_model=WebhookAcknowledgment,
    status_code=202,
)
async def receive_telephony_webhook(
    request: Request,
    timestamp: Annotated[
        str | None,
        Header(alias="X-ResQ-Timestamp"),
    ] = None,
    signature: Annotated[
        str | None,
        Header(alias="X-ResQ-Signature"),
    ] = None,
) -> WebhookAcknowledgment:
    """Authenticate and persist one incoming call event."""

    service = getattr(
        request.app.state,
        "telephony_ingestion_service",
        None,
    )

    if not isinstance(service, TelephonyWebhookIngestionService):
        logger.error("Telephony ingestion service is not configured")
        raise HTTPException(
            status_code=503,
            detail="Webhook service unavailable",
        )

    if timestamp is None or signature is None:
        raise HTTPException(
            status_code=401,
            detail="Missing webhook authentication headers",
        )

    # Read the exact original bytes. JSON must not be reserialized
    # before HMAC verification because even whitespace changes
    # would change the signature.
    body = await request.body()

    try:
        result = service.ingest(
            body=body,
            timestamp=timestamp,
            signature=signature,
        )

    except WebhookIngestionError as exc:
        # Do not leak detailed verification failures or secrets
        # through public HTTP responses.
        logger.warning(
            "Telephony webhook ingestion rejected: %s",
            type(exc).__name__,
        )

        if "Unable to persist" in str(exc):
            raise HTTPException(
                status_code=503,
                detail="Webhook persistence unavailable",
            ) from exc

        raise HTTPException(
            status_code=401,
            detail="Webhook authentication or validation failed",
        ) from exc

    return WebhookAcknowledgment(
        accepted=result.accepted,
        event_id=result.event_id,
        status=result.outcome,
    )
