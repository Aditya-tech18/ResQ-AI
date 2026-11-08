"""Authenticated audio upload endpoint."""

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentAuth
from app.services.audio_processing import (
    MAX_AUDIO_BYTES,
    AudioValidationError,
    validate_audio,
)

router = APIRouter(
    prefix="/api/v1/audio",
    tags=["Audio Processing"],
)


class AudioUploadResponse(BaseModel):
    status: str
    filename: str
    content_type: str
    size_bytes: int = Field(ge=1)
    sha256: str
    transcription_status: str


@router.post(
    "/upload",
    response_model=AudioUploadResponse,
)
async def upload_audio(
    auth: CurrentAuth,
    file: Annotated[UploadFile, File()],
) -> AudioUploadResponse:
    """Validate audio without retaining the uploaded recording."""

    _ = auth

    content_type = file.content_type or ""

    try:
        data = await file.read(MAX_AUDIO_BYTES + 1)

        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Audio exceeds 10 MB",
            )

        metadata = validate_audio(
            data=data,
            content_type=content_type,
        )

    except AudioValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    finally:
        await file.close()

    return AudioUploadResponse(
        status="validated",
        filename=metadata.filename,
        content_type=metadata.content_type,
        size_bytes=metadata.size_bytes,
        sha256=metadata.sha256,
        transcription_status="not_configured",
    )
