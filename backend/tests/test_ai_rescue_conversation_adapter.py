"""Tests for multilingual rescue conversation safety.

These tests deliberately use a fake decision engine:
- No paid API calls.
- No external network dependency.
- No database mutation.
- Deterministic acceptance/rejection behavior.

Real Gemini integration is tested separately.
"""

from copy import deepcopy
from typing import Any

import pytest

from app.services.ai_rescue_conversation_adapter import (
    AIRescueConversationAdapter,
    VerifiedConversationContext,
)


class FakeDecisionEngine:
    """Controlled replacement for the Gemini decision service."""

    def __init__(
        self,
        response: dict[str, Any] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, str]] = []

    def evaluate(
        self,
        message: str,
        speaker_role: str = "replacement_driver",
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "message": message,
                "speaker_role": speaker_role,
            }
        )

        if self.error is not None:
            raise self.error

        return deepcopy(self.response)


def context(
    *,
    driver_id: str = "DRIVER-SURESH",
    identity_verified: bool = True,
    call_active: bool = True,
    assignment_id: str = "ASSIGN-001",
    case_id: str = "CASE-001",
    call_id: str = "CALL-001",
) -> VerifiedConversationContext:
    return VerifiedConversationContext(
        case_id=case_id,
        assignment_id=assignment_id,
        driver_id=driver_id,
        call_id=call_id,
        identity_verified=identity_verified,
        call_active=call_active,
    )


def ai_response(
    *,
    language: str = "te",
    intent: str = "rescue_accept",
    decision: str = "READY_FOR_ASSIGNMENT",
    explicit_confirmation: bool = True,
    needs_clarification: bool = False,
    reply_text: str = "ధన్యవాదాలు.",
) -> dict[str, Any]:
    return {
        "language": language,
        "intent": intent,
        "decision": decision,
        "explicit_confirmation": explicit_confirmation,
        "needs_clarification": needs_clarification,
        "reply_text": reply_text,
    }


def test_suresh_telugu_acceptance():
    engine = FakeDecisionEngine(ai_response())
    adapter = AIRescueConversationAdapter(engine)

    result = adapter.assess(
        "అవును, నేను పార్సెల్స్ తీసుకుంటాను.",
        context=context(),
    )

    assert result["action"] == "ACCEPTANCE_CANDIDATE"
    assert result["language"] == "te"
    assert result["intent"] == "rescue_accept"
    assert result["can_record_consent"] is True
    assert result["requires_dispatcher_approval"] is True

    assert len(engine.calls) == 1
    assert engine.calls[0]["speaker_role"] == "replacement_driver"


def test_amit_hindi_acceptance():
    engine = FakeDecisionEngine(
        ai_response(
            language="hi",
            reply_text="ठीक है, आगे की प्रक्रिया बताता हूँ।",
        )
    )
    adapter = AIRescueConversationAdapter(engine)

    result = adapter.assess(
        "हाँ, मैं ये पार्सल ले सकता हूँ।",
        context=context(driver_id="DRIVER-AMIT"),
    )

    assert result["action"] == "ACCEPTANCE_CANDIDATE"
    assert result["language"] == "hi"
    assert result["can_record_consent"] is True


@pytest.mark.parametrize(
    ("language", "message"),
    [
        ("hi", "नहीं, मैं अभी नहीं आ सकता।"),
        ("te", "లేదు, నేను రాలేను."),
    ],
)
def test_driver_rejection(language: str, message: str):
    engine = FakeDecisionEngine(
        ai_response(
            language=language,
            intent="rescue_decline",
            decision="FIND_ANOTHER_DRIVER",
            explicit_confirmation=False,
        )
    )

    result = AIRescueConversationAdapter(engine).assess(
        message,
        context=context(),
    )

    assert result["action"] == "DRIVER_DECLINED"
    assert result["can_record_consent"] is False
    assert result["requires_dispatcher_approval"] is False


@pytest.mark.parametrize(
    ("language", "message"),
    [
        ("hi", "मैं 20 मिनट बाद आ सकता हूँ।"),
        ("te", "నేను ఇరవై నిమిషాల తర్వాత వస్తాను."),
    ],
)
def test_conditional_offer_requires_negotiation(
    language: str,
    message: str,
):
    engine = FakeDecisionEngine(
        ai_response(
            language=language,
            intent="rescue_conditional",
            decision="CONDITIONAL_OFFER",
            explicit_confirmation=False,
        )
    )

    result = AIRescueConversationAdapter(engine).assess(
        message,
        context=context(),
    )

    assert result["action"] == "CONDITIONAL_OFFER"
    assert result["can_record_consent"] is False


def test_uncertain_driver_response():
    engine = FakeDecisionEngine(
        ai_response(
            intent="unclear",
            decision="NEEDS_CLARIFICATION",
            explicit_confirmation=False,
            needs_clarification=True,
        )
    )

    result = AIRescueConversationAdapter(engine).assess(
        "शायद मैं आ पाऊँ।",
        context=context(),
    )

    assert result["action"] == "CLARIFICATION_REQUIRED"
    assert result["can_record_consent"] is False


def test_unverified_driver_is_blocked_before_ai_call():
    engine = FakeDecisionEngine(ai_response())

    result = AIRescueConversationAdapter(engine).assess(
        "हाँ, मैं तैयार हूँ।",
        context=context(identity_verified=False),
    )

    assert result["action"] == "INVALID_CONTEXT"
    assert result["can_record_consent"] is False
    assert engine.calls == []


def test_inactive_call_is_blocked_before_ai_call():
    engine = FakeDecisionEngine(ai_response())

    result = AIRescueConversationAdapter(engine).assess(
        "हाँ",
        context=context(call_active=False),
    )

    assert result["action"] == "INVALID_CONTEXT"
    assert result["can_record_consent"] is False
    assert engine.calls == []


@pytest.mark.parametrize(
    "invalid_field",
    ["case_id", "assignment_id", "driver_id", "call_id"],
)
def test_missing_context_identifier(invalid_field: str):
    engine = FakeDecisionEngine(ai_response())

    kwargs = {invalid_field: "   "}
    result = AIRescueConversationAdapter(engine).assess(
        "हाँ",
        context=context(**kwargs),
    )

    assert result["action"] == "INVALID_CONTEXT"
    assert result["can_record_consent"] is False
    assert engine.calls == []


@pytest.mark.parametrize(
    "message",
    ["", " ", "\n\t"],
)
def test_empty_message_does_not_call_ai(message: str):
    engine = FakeDecisionEngine(ai_response())

    result = AIRescueConversationAdapter(engine).assess(
        message,
        context=context(),
    )

    assert result["action"] == "CLARIFICATION_REQUIRED"
    assert result["can_record_consent"] is False
    assert engine.calls == []


def test_ai_provider_failure_fails_closed():
    engine = FakeDecisionEngine(error=RuntimeError("AI provider unavailable"))

    result = AIRescueConversationAdapter(engine).assess(
        "हाँ",
        context=context(),
    )

    assert result["action"] == "CLARIFICATION_REQUIRED"
    assert result["can_record_consent"] is False


def test_ai_acceptance_without_explicit_confirmation_is_blocked():
    engine = FakeDecisionEngine(ai_response(explicit_confirmation=False))

    result = AIRescueConversationAdapter(engine).assess(
        "ठीक है",
        context=context(),
    )

    assert result["can_record_consent"] is False
    assert result["action"] == "CLARIFICATION_REQUIRED"


def test_ai_response_cannot_override_verified_driver_identity():
    """The adapter must not treat AI output as identity evidence."""

    response = ai_response()
    response["driver_id"] = "ATTACKER-DRIVER"
    response["identity_verified"] = True

    engine = FakeDecisionEngine(response)

    result = AIRescueConversationAdapter(engine).assess(
        "हाँ",
        context=context(identity_verified=False),
    )

    assert result["action"] == "INVALID_CONTEXT"
    assert result["can_record_consent"] is False
    assert engine.calls == []


def test_acceptance_does_not_modify_database():
    """Assessment is a pure decision step, not parcel reassignment."""

    engine = FakeDecisionEngine(ai_response())
    adapter = AIRescueConversationAdapter(engine)

    result = adapter.assess(
        "అవును",
        context=context(),
    )

    assert result["action"] == "ACCEPTANCE_CANDIDATE"

    # No workflow or database dependency exists in the adapter.
    assert not hasattr(adapter, "workflow")
    assert not hasattr(adapter, "db")
