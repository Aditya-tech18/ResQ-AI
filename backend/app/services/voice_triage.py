"""Merchant-scoped voice exception triage."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.shipment import Shipment
from app.services.voice_intelligence import (
    VoiceAnalysis,
    analyze_transcript,
)


def triage_shipment(
    db: Session,
    *,
    merchant_id: str,
    shipment_id: UUID,
    transcript: str,
) -> VoiceAnalysis:
    """Return an analysis only for a shipment owned by the merchant."""

    shipment = db.scalar(
        select(Shipment).where(
            Shipment.id == str(shipment_id),
            Shipment.merchant_id == str(merchant_id),
        )
    )

    if shipment is None:
        raise HTTPException(
            status_code=404,
            detail="Shipment not found",
        )

    return analyze_transcript(transcript)
