"""ResQ AI: real Gnani Prisma and Timbre REST gateway.

Mount router on existing FastAPI app. Never send Gnani keys to browsers.
"""
from __future__ import annotations

import os
import asyncio
import shutil
from typing import Annotated

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v8/voice", tags=["Gnani voice"])
BASE = "https://api.vachana.ai"
LANGUAGES = {"hi-IN", "te-IN", "en-IN", "hi-en", "indic-auto"}
VOICES = {
    "female": "Shivani", "male": "Avinash",
}
MAX_AUDIO = 8 * 1024 * 1024


def _key() -> str:
    key = os.getenv("GNANI_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "GNANI_API_KEY not configured")
    return key


def _upstream_error(exc: Exception) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        # Avoid leaking provider details or credentials to the browser.
        return HTTPException(502 if status < 500 else 503, f"Gnani service returned HTTP {status}")
    return HTTPException(503, "Gnani service unreachable or timed out")


@router.post("/transcribe")
async def transcribe(
    audio: Annotated[UploadFile, File(description="WAV/MP3/OGG/M4A; max 30 seconds")],
    language: Annotated[str, Form()] = "indic-auto",
):
    if language not in LANGUAGES:
        raise HTTPException(422, "Unsupported language hint")
    filename = (audio.filename or "recording.wav").lower()
    if not filename.endswith((".wav", ".mp3", ".ogg", ".m4a", ".flac", ".aac", ".webm")):
        raise HTTPException(422, "Unsupported audio format")
    data = await audio.read(MAX_AUDIO + 1)
    if not data or len(data) > MAX_AUDIO:
        raise HTTPException(413, "Audio empty or exceeds 8MB")
    if filename.endswith(".webm"):
        if not shutil.which("ffmpeg"):
            raise HTTPException(422, "Browser WebM audio requires ffmpeg: brew install ffmpeg")
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", "pipe:0", "-ac", "1", "-ar", "16000",
            "-f", "wav", "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            wav, errors = await asyncio.wait_for(process.communicate(data), timeout=20)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise HTTPException(422, 'Audio conversion exceeded 20 seconds')
        if process.returncode != 0 or not wav or len(wav) > MAX_AUDIO:
            raise HTTPException(422, "Unable to convert browser recording to WAV")
        data = wav
        filename = "recording.wav"
    key = _key()
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                BASE + "/stt/v3",
                headers={"X-API-Key-ID": key},
                files={"audio_file": (filename, data, audio.content_type or "application/octet-stream")},
                data={
                    "model": os.getenv("RESQ_PRISMA_MODEL", "prisma-v3.0"),
                    "language_code": language,
                    "format": "codemix" if language in {"hi-IN", "hi-en", "indic-auto"} else "transcribe",
                    "topic": "Delivery rescue coordination; parcel quantity, pickup ETA, route, destination and explicit call-end consent",
                    "keyterms": '["parcel","pickup","route","delivery"]',
                },
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise _upstream_error(exc) from exc
    if not isinstance(result.get("transcript"), str):
        raise HTTPException(502, "Unexpected Prisma response")
    return {
        "transcript": result["transcript"],
        "language": result.get("detected_language_code"),
        "model": result.get("model", os.getenv("RESQ_PRISMA_MODEL", "prisma-v3.0")),
        "provider": "gnani",
    }


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1800)
    language: str = "hi-IN"
    gender: str = "female"


@router.post("/speak")
async def speak(payload: SpeechRequest):
    if payload.language not in {"hi-IN", "te-IN", "en-IN", "hi-en"}:
        raise HTTPException(422, "Unsupported TTS language")
    if payload.gender not in VOICES:
        raise HTTPException(422, "Gender must be male or female")
    key = _key()
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                BASE + "/api/v1/tts/inference",
                headers={"X-API-Key-ID": key},
                json={
                    "text": payload.text,
                    "voice": VOICES[payload.gender],
                    "model": os.getenv("RESQ_TIMBRE_MODEL", "timbre-v3.0"),
                    "language": payload.language,
                    "speed": 1.0,
                    "audio_config": {
                        "encoding": "linear_pcm", "container": "wav",
                        "num_channels": 1, "sample_rate": 24000, "sample_width": 2,
                    },
                },
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise _upstream_error(exc) from exc
    content_type = response.headers.get("content-type", "")
    if "audio/" not in content_type and not response.content.startswith(b"RIFF"):
        raise HTTPException(502, "Unexpected Timbre audio response")
    return Response(
        content=response.content,
        media_type="audio/wav",
        headers={"X-ResQ-TTS-Provider": "gnani-timbre-v3.0", "Cache-Control": "no-store"},
    )


@router.get("/status")
async def status():
    return {
        "gnani_key_configured": bool(os.getenv("GNANI_API_KEY", "").strip()),
        "prisma_model": os.getenv("RESQ_PRISMA_MODEL", "prisma-v3.0"), "timbre_model": os.getenv("RESQ_TIMBRE_MODEL", "timbre-v3.0"),
        "real_phone_calling": False,
        "note": "Configured is not proof of successful provider access. Test transcribe and speak.",
    }
