"""Audio validation and secure temporary storage."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_AUDIO_BYTES = 10 * 1024 * 1024

SUPPORTED_CONTENT_TYPES = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
}


class AudioValidationError(ValueError):
    """Invalid audio upload."""


@dataclass(frozen=True)
class AudioMetadata:
    filename: str
    content_type: str
    size_bytes: int
    sha256: str


def validate_audio(
    data: bytes,
    content_type: str,
) -> AudioMetadata:
    """Validate size, MIME type and basic audio signatures."""

    normalized_type = content_type.split(";", 1)[0].strip().lower()

    if normalized_type not in SUPPORTED_CONTENT_TYPES:
        raise AudioValidationError("Unsupported audio content type")

    if not data:
        raise AudioValidationError("Audio file is empty")

    if len(data) > MAX_AUDIO_BYTES:
        raise AudioValidationError("Audio exceeds 10 MB")

    signatures = {
        "audio/wav": data.startswith(b"RIFF") and data[8:12] == b"WAVE",
        "audio/x-wav": data.startswith(b"RIFF") and data[8:12] == b"WAVE",
        "audio/mpeg": data.startswith(b"ID3")
        or data.startswith(b"\xff\xfb")
        or data.startswith(b"\xff\xf3")
        or data.startswith(b"\xff\xf2"),
        "audio/mp4": len(data) >= 12 and data[4:8] == b"ftyp",
        "audio/ogg": data.startswith(b"OggS"),
        "audio/webm": data.startswith(b"\x1a\x45\xdf\xa3"),
    }

    if not signatures[normalized_type]:
        raise AudioValidationError("Audio content does not match declared format")

    return AudioMetadata(
        filename="audio" + SUPPORTED_CONTENT_TYPES[normalized_type],
        content_type=normalized_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def save_temporary_audio(
    data: bytes,
    metadata: AudioMetadata,
) -> Path:
    """Store validated audio in a private temporary file."""

    suffix = Path(metadata.filename).suffix

    fd, filename = tempfile.mkstemp(
        prefix="dispatchresolve_",
        suffix=suffix,
    )

    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)

        os.chmod(filename, 0o600)

    except Exception:
        Path(filename).unlink(missing_ok=True)
        raise

    return Path(filename)
