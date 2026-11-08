"""Rule-based multilingual pickup-exception analysis.

This is a deterministic baseline, not a trained ML model.
It does not transcribe audio or execute operational actions.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field


class VoiceReason(StrEnum):
    CUSTOMER_UNAVAILABLE = "customer_unavailable"
    ADDRESS_ISSUE = "address_issue"
    GATE_CLOSED = "gate_closed"
    PICKUP_DELAY = "pickup_delay"
    PACKAGE_NOT_READY = "package_not_ready"
    UNKNOWN = "unknown"


class SuggestedAction(StrEnum):
    RESCHEDULE_PICKUP = "reschedule_pickup"
    VERIFY_ADDRESS = "verify_address"
    CONTACT_SECURITY = "contact_security"
    FOLLOW_UP_WITH_DRIVER = "follow_up_with_driver"
    CONTACT_CUSTOMER = "contact_customer"
    MANUAL_REVIEW = "manual_review"


class VoiceAnalysis(BaseModel):
    transcript: str
    language_hint: str
    reason: VoiceReason
    suggested_action: SuggestedAction
    confidence: float = Field(ge=0, le=1)
    requires_human_review: bool
    matched_keywords: list[str]
    processing_method: str = "rule_based_v1"


RULES: tuple[
    tuple[VoiceReason, SuggestedAction, tuple[str, ...]],
    ...,
] = (
    (
        VoiceReason.ADDRESS_ISSUE,
        SuggestedAction.VERIFY_ADDRESS,
        (
            "wrong address",
            "incorrect address",
            "address galat",
            "galat address",
            "location nahi mil",
            "address nahi mil",
            "पता गलत",
            "गलत पता",
        ),
    ),
    (
        VoiceReason.GATE_CLOSED,
        SuggestedAction.CONTACT_SECURITY,
        (
            "gate closed",
            "gate band",
            "gate nahi khul",
            "security ne roka",
            "entry denied",
            "गेट बंद",
        ),
    ),
    (
        VoiceReason.CUSTOMER_UNAVAILABLE,
        SuggestedAction.RESCHEDULE_PICKUP,
        (
            "customer unavailable",
            "customer not available",
            "customer absent",
            "customer ghar pe nahi",
            "customer nahi mila",
            "customer nahi tha",
            "customer available nahi",
            "customer not home",
            "ग्राहक नहीं मिला",
            "ग्राहक घर पर नहीं",
        ),
    ),
    (
        VoiceReason.PACKAGE_NOT_READY,
        SuggestedAction.CONTACT_CUSTOMER,
        (
            "package not ready",
            "parcel not ready",
            "parcel ready nahi",
            "package ready nahi",
            "parcel taiyar nahi",
            "पार्सल तैयार नहीं",
        ),
    ),
    (
        VoiceReason.PICKUP_DELAY,
        SuggestedAction.FOLLOW_UP_WITH_DRIVER,
        (
            "pickup delayed",
            "pickup late",
            "traffic jam",
            "traffic mein",
            "late ho gaya",
            "pickup nahi ho paya",
            "पिकअप लेट",
            "ट्रैफिक जाम",
        ),
    ),
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _language_hint(text: str) -> str:
    if re.search(r"[\u0900-\u097f]", text):
        return "hi"

    hinglish_terms = (
        "nahi",
        "galat",
        "ghar",
        "kal",
        "baje",
        "band",
        "mila",
        "karunga",
        "ho gaya",
        "taiyar",
    )

    normalized = _normalize(text)

    if any(re.search(rf"\b{re.escape(term)}\b", normalized) for term in hinglish_terms):
        return "hinglish"

    return "en"


def analyze_transcript(transcript: str) -> VoiceAnalysis:
    """Classify a transcript without calling external services."""

    normalized = _normalize(transcript)

    if not normalized:
        raise ValueError("Transcript cannot be empty")

    candidates = []

    for reason, action, keywords in RULES:
        matched = [keyword for keyword in keywords if keyword in normalized]

        if matched:
            candidates.append((reason, action, matched))

    if not candidates:
        return VoiceAnalysis(
            transcript=transcript,
            language_hint=_language_hint(transcript),
            reason=VoiceReason.UNKNOWN,
            suggested_action=SuggestedAction.MANUAL_REVIEW,
            confidence=0.0,
            requires_human_review=True,
            matched_keywords=[],
        )

    # Multiple reason categories are ambiguous.
    # Choose the strongest match, but flag for review.
    candidates.sort(
        key=lambda item: (
            max(len(keyword) for keyword in item[2]),
            len(item[2]),
        ),
        reverse=True,
    )

    reason, action, matched = candidates[0]
    ambiguous = len(candidates) > 1

    return VoiceAnalysis(
        transcript=transcript,
        language_hint=_language_hint(transcript),
        reason=reason,
        suggested_action=action,
        confidence=0.55 if ambiguous else 0.75,
        requires_human_review=ambiguous,
        matched_keywords=matched,
    )
