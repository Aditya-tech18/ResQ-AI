"""Convert Gemini driver conversations into safe rescue decisions."""

from __future__ import annotations

from typing import Any

from app.services.gemini_multilingual_engine import GeminiMultilingualEngine


class RescueDecisionService:
    def __init__(self) -> None:
        self.engine = GeminiMultilingualEngine()

    def evaluate(
        self,
        message: str,
        speaker_role: str = "replacement_driver",
    ) -> dict[str, Any]:
        result = self.engine.analyze(
            message,
            speaker_role=speaker_role,
        )

        intent = result.intent
        confirmed = result.explicit_confirmation
        clarification = result.needs_clarification
        delay = result.delay_minutes

        # Never assign a parcel without explicit acceptance.
        if (
            speaker_role == "replacement_driver"
            and confirmed
            and not clarification
            and intent == "rescue_accept"
        ):
            decision = "READY_FOR_ASSIGNMENT"
            requires_dispatcher_approval = True

        elif intent == "rescue_conditional":
            decision = "CONDITIONAL_OFFER"
            requires_dispatcher_approval = True

        elif intent in {"rescue_reject", "rescue_decline"}:
            decision = "FIND_ANOTHER_DRIVER"
            requires_dispatcher_approval = False

        else:
            decision = "NEEDS_CLARIFICATION"
            requires_dispatcher_approval = False

        return {
            "language": result.language,
            "intent": intent,
            "decision": decision,
            "explicit_confirmation": confirmed,
            "needs_clarification": clarification,
            "delay_minutes": delay,
            "requires_dispatcher_approval": requires_dispatcher_approval,
            "reply_text": result.reply_text,
            "reason": result.reason,
        }


if __name__ == "__main__":
    service = RescueDecisionService()

    examples = [
        (
            "TELUGU CONDITIONAL",
            "నేను ఒక గంట తర్వాత వస్తాను, ఇప్పుడే రాలేను.",
        ),
        (
            "HINDI ACCEPTANCE",
            "हाँ, मैं दोनों पार्सल डिलीवर कर दूंगा।",
        ),
        (
            "HINDI REJECTION",
            "नहीं, मैं आज डिलीवरी नहीं कर सकता।",
        ),
    ]

    for label, message in examples:
        print(f"\n=== {label} ===")

        try:
            result = service.evaluate(message)

            for key, value in result.items():
                print(f"{key}: {value}")

        except Exception as exc:
            print("ERROR TYPE:", type(exc).__name__)
            print("ERROR:", str(exc)[:300])
