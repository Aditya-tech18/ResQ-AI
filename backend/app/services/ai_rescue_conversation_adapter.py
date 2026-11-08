"""Safely interpret multilingual rescue-driver conversations.

This module separates AI interpretation from operational authorization.

The AI model may classify a driver's response, but it must not
independently authenticate the speaker or modify parcel assignments.

A trusted call provider or authenticated driver application must
establish speaker identity before consent can be persisted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class ConversationAction(StrEnum):
    ACCEPTANCE_CANDIDATE = "ACCEPTANCE_CANDIDATE"
    DRIVER_DECLINED = "DRIVER_DECLINED"
    CONDITIONAL_OFFER = "CONDITIONAL_OFFER"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    INVALID_CONTEXT = "INVALID_CONTEXT"


@dataclass(frozen=True, slots=True)
class VerifiedConversationContext:
    """Identifiers obtained from trusted operational systems."""

    case_id: str
    assignment_id: str
    driver_id: str
    call_id: str
    identity_verified: bool
    call_active: bool


@dataclass(frozen=True, slots=True)
class ConversationAssessment:
    action: ConversationAction
    language: str
    intent: str
    reply_text: str
    can_record_consent: bool
    requires_dispatcher_approval: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "language": self.language,
            "intent": self.intent,
            "reply_text": self.reply_text,
            "can_record_consent": self.can_record_consent,
            "requires_dispatcher_approval": (self.requires_dispatcher_approval),
            "reason": self.reason,
        }


class DecisionEngine(Protocol):
    def evaluate(
        self,
        message: str,
        speaker_role: str = "replacement_driver",
    ) -> Mapping[str, Any]: ...


class AIRescueConversationAdapter:
    """Interpret driver responses without performing DB mutations."""

    def __init__(self, decision_engine: DecisionEngine) -> None:
        self.decision_engine = decision_engine

    @staticmethod
    def _valid_identifier(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @classmethod
    def _valid_context(
        cls,
        context: VerifiedConversationContext,
    ) -> bool:
        if not isinstance(context, VerifiedConversationContext):
            return False

        return all(
            cls._valid_identifier(value)
            for value in (
                context.case_id,
                context.assignment_id,
                context.driver_id,
                context.call_id,
            )
        )

    @staticmethod
    def _assessment(
        action: ConversationAction,
        *,
        language: str = "unknown",
        intent: str = "unknown",
        reply_text: str = "",
        can_record_consent: bool = False,
        requires_dispatcher_approval: bool = False,
        reason: str,
    ) -> dict[str, Any]:
        return ConversationAssessment(
            action=action,
            language=language,
            intent=intent,
            reply_text=reply_text,
            can_record_consent=can_record_consent,
            requires_dispatcher_approval=(requires_dispatcher_approval),
            reason=reason,
        ).to_dict()

    def assess(
        self,
        message: str,
        *,
        context: VerifiedConversationContext,
    ) -> dict[str, Any]:
        """Classify a response without changing operational state.

        A positive result indicates eligibility for a separate,
        authenticated workflow operation. It is not itself consent
        persistence or dispatcher authorization.
        """

        if not isinstance(message, str) or not message.strip():
            return self._assessment(
                ConversationAction.CLARIFICATION_REQUIRED,
                reason="Driver response is empty.",
            )

        if not self._valid_context(context):
            return self._assessment(
                ConversationAction.INVALID_CONTEXT,
                reason="Conversation identifiers are invalid.",
            )

        # Identity verification must come from a trusted channel.
        # AI language classification is not identity verification.
        if context.identity_verified is not True or context.call_active is not True:
            return self._assessment(
                ConversationAction.INVALID_CONTEXT,
                reason=("An active, authenticated driver session is required."),
            )

        try:
            decision = self.decision_engine.evaluate(
                message,
                speaker_role="replacement_driver",
            )
        except Exception:
            # Fail closed. Never authorize consent after AI failure.
            return self._assessment(
                ConversationAction.CLARIFICATION_REQUIRED,
                reason="AI interpretation unavailable.",
            )

        if not isinstance(decision, Mapping):
            return self._assessment(
                ConversationAction.CLARIFICATION_REQUIRED,
                reason="AI returned an invalid response.",
            )

        language = decision.get("language", "unknown")
        intent = decision.get("intent", "unknown")
        reply_text = decision.get("reply_text", "")

        language = language if isinstance(language, str) else "unknown"
        intent = intent if isinstance(intent, str) else "unknown"
        reply_text = reply_text if isinstance(reply_text, str) else ""

        if decision.get("needs_clarification") is not False:
            return self._assessment(
                ConversationAction.CLARIFICATION_REQUIRED,
                language=language,
                intent=intent,
                reply_text=reply_text,
                reason="Driver intent needs clarification.",
            )

        if (
            decision.get("decision") == "READY_FOR_ASSIGNMENT"
            and intent == "rescue_accept"
            and decision.get("explicit_confirmation") is True
        ):
            return self._assessment(
                ConversationAction.ACCEPTANCE_CANDIDATE,
                language=language,
                intent=intent,
                reply_text=reply_text,
                can_record_consent=True,
                requires_dispatcher_approval=True,
                reason=("Verified session and explicit acceptance passed preliminary checks."),
            )

        if decision.get("decision") == "FIND_ANOTHER_DRIVER" and intent == "rescue_decline":
            return self._assessment(
                ConversationAction.DRIVER_DECLINED,
                language=language,
                intent=intent,
                reply_text=reply_text,
                reason="Driver declined the rescue assignment.",
            )

        if decision.get("decision") == "CONDITIONAL_OFFER" and intent == "rescue_conditional":
            return self._assessment(
                ConversationAction.CONDITIONAL_OFFER,
                language=language,
                intent=intent,
                reply_text=reply_text,
                reason=("Conditional availability requires additional negotiation."),
            )

        return self._assessment(
            ConversationAction.CLARIFICATION_REQUIRED,
            language=language,
            intent=intent,
            reply_text=reply_text,
            reason="No unambiguous driver decision was identified.",
        )
