"""Gnani Prisma STT + Gemini reasoning + Gnani Timbre TTS."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from gnani.stt.batch import GnaniSTTBatchClient
from gnani.tts.client import GnaniTTSClient

from app.services.gemini_multilingual_engine import (
    GeminiMultilingualEngine,
)

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


class GnaniVoiceService:
    def __init__(self) -> None:
        key = os.getenv("GNANI_API_KEY", "").strip()

        if not key:
            raise RuntimeError("GNANI_API_KEY is missing.")

        self.stt = GnaniSTTBatchClient(
            api_key=os.getenv("GNANI_STT_API_KEY") or key,
            base_url=(os.getenv("GNANI_STT_ENDPOINT") or "https://api.vachana.ai"),
            timeout=int(os.getenv("GNANI_TIMEOUT_SECONDS") or "60"),
        )

        self.tts = GnaniTTSClient(
            api_key=os.getenv("GNANI_TTS_API_KEY") or key,
            base_url=(os.getenv("GNANI_TTS_ENDPOINT") or "https://api.vachana.ai"),
            timeout=int(os.getenv("GNANI_TIMEOUT_SECONDS") or "60"),
        )

        self.gemini = GeminiMultilingualEngine()

    def transcribe(
        self,
        audio_path: str | Path,
        language_code: str = "te-IN",
    ) -> str:
        path = Path(audio_path).resolve()

        if not path.is_file():
            raise FileNotFoundError(f"Audio file missing: {path}")

        print("GNANI PRISMA: Transcribing audio...")

        result = self.stt.transcribe(
            files=str(path),
            language_code=language_code,
            progress=False,
            timeout=120,
        )

        texts = []

        for item in result.files:
            transcript = getattr(item, "_transcript", None)

            if not transcript:
                continue

            if isinstance(transcript, dict):
                segments = transcript.get("segments", [])

                for segment in segments:
                    if isinstance(segment, dict):
                        text = segment.get("text", "")
                        if text:
                            texts.append(text)

                if not texts:
                    text = transcript.get("text", "")
                    if text:
                        texts.append(text)

        transcription = " ".join(texts).strip()

        if not transcription:
            raise RuntimeError(
                "Gnani transcription was empty. Inspect the returned batch transcript format."
            )

        return transcription

    def synthesize(
        self,
        text: str,
        output_path: str | Path,
        language: str = "te",
    ) -> Path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        print("GNANI TIMBRE: Generating speech...")

        audio = self.tts.synthesize(
            text=text,
            voice=os.getenv("GNANI_TTS_VOICE") or "Pranav",
            model=os.getenv("GNANI_TTS_MODEL") or "timbre-v2.5",
            language=language,
        )

        if not audio:
            raise RuntimeError("Gnani TTS returned empty audio.")

        output.write_bytes(audio)
        return output

    def process_voice(
        self,
        audio_path: str | Path,
        *,
        speaker_role: Literal[
            "driver",
            "replacement_driver",
            "customer",
            "dispatcher",
        ] = "replacement_driver",
        input_language: str = "te-IN",
        output_path: str | Path = "data/voice_demo/ai_reply.wav",
    ) -> dict:
        transcript = self.transcribe(
            audio_path,
            language_code=input_language,
        )

        print("TRANSCRIPT:", transcript)

        result = self.gemini.analyze(
            transcript,
            speaker_role=speaker_role,
        )

        print("DETECTED LANGUAGE:", result.language)
        print("INTENT:", result.intent)
        print("AI REPLY:", result.reply_text)

        speech_language = {
            "te": "te-IN",
            "hi": "hi-IN",
            "en": "en-IN",
            "ta": "ta-IN",
            "kn": "kn-IN",
            "ml": "ml-IN",
        }.get(result.language, "hi-IN")

        audio_file = self.synthesize(
            result.reply_text,
            output_path=output_path,
            language=speech_language,
        )

        return {
            "transcript": transcript,
            "language": result.language,
            "intent": result.intent,
            "driver_response": result.driver_response,
            "delay_minutes": result.delay_minutes,
            "reply_text": result.reply_text,
            "reply_audio": str(audio_file),
        }


if __name__ == "__main__":
    service = GnaniVoiceService()
    print("GNANI VOICE SERVICE INITIALIZED")
    print("STT: Prisma")
    print("AI: Gemini")
    print("TTS: Timbre")
    print("Ready for audio-file testing.")
