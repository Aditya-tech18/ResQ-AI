"""Authenticated voice transcript analysis API."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentAuth
from app.services.voice_intelligence import (
    VoiceAnalysis,
    analyze_transcript,
)

router = APIRouter(
    prefix="/api/v1/voice",
    tags=["Voice Intelligence"],
)


class TranscriptRequest(BaseModel):
    transcript: str = Field(
        min_length=1,
        max_length=5000,
    )


@router.post(
    "/analyze",
    response_model=VoiceAnalysis,
)
def analyze_voice_transcript(
    payload: TranscriptRequest,
    auth: CurrentAuth,
) -> VoiceAnalysis:
    """Analyze text from an authenticated merchant user."""
    _ = auth
    return analyze_transcript(payload.transcript)


# DISPATCHRESOLVE_SHIPMENT_TRIAGE_V1
from uuid import UUID  # noqa: E402

from app.api.dependencies import DBSession  # noqa: E402
from app.services.voice_triage import triage_shipment  # noqa: E402


class ShipmentTriageRequest(BaseModel):
    shipment_id: UUID
    transcript: str = Field(min_length=1, max_length=5000)


@router.post(
    "/triage",
    response_model=VoiceAnalysis,
)
def triage_voice_exception(
    payload: ShipmentTriageRequest,
    auth: CurrentAuth,
    db: DBSession,
) -> VoiceAnalysis:
    return triage_shipment(
        db,
        merchant_id=auth.merchant_id,
        shipment_id=payload.shipment_id,
        transcript=payload.transcript,
    )


# DISPATCHRESOLVE_BULK_TRIAGE_V1
from collections import Counter  # noqa: E402

from fastapi import HTTPException  # noqa: E402


class BulkTriageItem(BaseModel):
    shipment_id: UUID
    transcript: str = Field(min_length=1, max_length=5000)


class BulkTriageRequest(BaseModel):
    items: list[BulkTriageItem] = Field(
        min_length=1,
        max_length=50,
    )


class BulkTriageResult(BaseModel):
    shipment_id: UUID
    status: str
    analysis: VoiceAnalysis | None = None


class BulkTriageResponse(BaseModel):
    total: int
    analyzed: int
    not_found: int
    human_review_required: int
    reason_counts: dict[str, int]
    results: list[BulkTriageResult]


@router.post(
    "/bulk-triage",
    response_model=BulkTriageResponse,
)
def bulk_triage(
    payload: BulkTriageRequest,
    auth: CurrentAuth,
    db: DBSession,
) -> BulkTriageResponse:
    """Analyze up to 50 merchant-owned shipment reports."""

    results = []
    counts: Counter[str] = Counter()
    analyzed = 0
    not_found = 0
    review_count = 0

    for item in payload.items:
        try:
            analysis = triage_shipment(
                db,
                merchant_id=auth.merchant_id,
                shipment_id=item.shipment_id,
                transcript=item.transcript,
            )

        except HTTPException as exc:
            if exc.status_code != 404:
                raise

            not_found += 1

            results.append(
                BulkTriageResult(
                    shipment_id=item.shipment_id,
                    status="not_found",
                )
            )
            continue

        analyzed += 1
        counts[analysis.reason.value] += 1

        if analysis.requires_human_review:
            review_count += 1

        results.append(
            BulkTriageResult(
                shipment_id=item.shipment_id,
                status="analyzed",
                analysis=analysis,
            )
        )

    return BulkTriageResponse(
        total=len(payload.items),
        analyzed=analyzed,
        not_found=not_found,
        human_review_required=review_count,
        reason_counts=dict(counts),
        results=results,
    )


# DISPATCHRESOLVE_BULK_TRIAGE_V1


class BulkTriageItem(BaseModel):
    shipment_id: UUID
    transcript: str = Field(min_length=1, max_length=5000)


class BulkTriageRequest(BaseModel):
    items: list[BulkTriageItem] = Field(
        min_length=1,
        max_length=50,
    )


class BulkTriageResult(BaseModel):
    shipment_id: UUID
    status: str
    analysis: VoiceAnalysis | None = None


class BulkTriageResponse(BaseModel):
    total: int
    analyzed: int
    not_found: int
    human_review_required: int
    reason_counts: dict[str, int]
    results: list[BulkTriageResult]
