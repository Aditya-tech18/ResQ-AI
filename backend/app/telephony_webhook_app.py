"""Standalone FastAPI application for testing webhook ingestion.

Production integration should mount the router in the existing
ResQ AI app and configure the ingestion service at startup.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from app.api.telephony_webhooks import router
from app.services.telephony_event_inbox import TelephonyEventInbox
from app.services.telephony_webhook_ingestion import (
    TelephonyWebhookIngestionService,
)


def create_telephony_webhook_app(
    *,
    secret: str | bytes,
    database_path: str | Path,
) -> FastAPI:
    """Build a webhook-only FastAPI application."""

    app = FastAPI(
        title="ResQ AI Telephony Webhook Gateway",
        version="0.1.0",
    )

    inbox = TelephonyEventInbox(database_path)

    ingestion_service = TelephonyWebhookIngestionService(
        secret=secret,
        inbox=inbox,
    )

    app.state.telephony_inbox = inbox
    app.state.telephony_ingestion_service = ingestion_service

    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
