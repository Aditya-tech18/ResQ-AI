"""Security tests for AI-assisted rescue approval."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.ai_rescue_approval_gate import (
    AIRescueApprovalGate,
    RescueApprovalContext,
)

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def accepted_decision(**overrides):
    """Build a valid, assignment-bound driver acceptance."""

    decision = {
        "intent": "rescue_accept",
        "decision": "READY_FOR_ASSIGNMENT",
        "explicit_confirmation": True,
        "needs_clarification": False,
        "case_id": "CASE-001",
        "driver_id": "DRIVER-SURESH",
        "assignment_id": "ASSIGN-001",
    }

    decision.update(overrides)
    return decision


def trusted_context(**overrides):
    """Build trusted context supplied by the rescue workflow."""

    context = {
        "case_id": "CASE-001",
        "driver_id": "DRIVER-SURESH",
        "assignment_id": "ASSIGN-001",
        "consent_recorded_at": NOW - timedelta(minutes=5),
        "dispatcher_id": "DISPATCHER-001",
        "dispatcher_approved_at": NOW - timedelta(minutes=1),
    }

    context.update(overrides)
    return RescueApprovalContext(**context)


def evaluate(
    decision=None,
    *,
    context=None,
    dispatcher_approved=True,
    now=NOW,
):
    if decision is None:
        decision = accepted_decision()

    if context is None:
        context = trusted_context()

    return AIRescueApprovalGate.evaluate(
        decision,
        context=context,
        dispatcher_approved=dispatcher_approved,
        now=now,
    )


def test_valid_driver_and_dispatcher_approval():
    result = evaluate()

    assert result["can_commit"] is True
    assert result["status"] == "AUTHORIZED_FOR_COMMIT"
    assert result["reason_code"] == "AUTHORIZED"


def test_driver_acceptance_without_dispatcher_approval():
    result = evaluate(dispatcher_approved=False)

    assert result["can_commit"] is False
    assert result["status"] == "AWAITING_DISPATCHER_APPROVAL"


def test_legacy_boolean_cannot_authorize_commit():
    result = AIRescueApprovalGate.evaluate(
        accepted_decision(),
        dispatcher_approved=True,
    )

    assert result["can_commit"] is False


@pytest.mark.parametrize(
    ("intent", "decision_status"),
    [
        ("rescue_decline", "FIND_ANOTHER_DRIVER"),
        ("rescue_conditional", "CONDITIONAL_OFFER"),
        ("unknown", "NEEDS_CLARIFICATION"),
    ],
)
def test_non_acceptance_is_blocked(intent, decision_status):
    result = evaluate(
        accepted_decision(
            intent=intent,
            decision=decision_status,
            explicit_confirmation=False,
        )
    )

    assert result["can_commit"] is False
    assert result["status"] == "BLOCKED"


def test_missing_explicit_confirmation():
    result = evaluate(accepted_decision(explicit_confirmation=False))

    assert result["can_commit"] is False


def test_clarification_required():
    result = evaluate(accepted_decision(needs_clarification=True))

    assert result["can_commit"] is False


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("case_id", "CASE-999"),
        ("driver_id", "DRIVER-AMIT"),
        ("assignment_id", "ASSIGN-999"),
    ],
)
def test_cross_assignment_consent_reuse_blocked(field, wrong_value):
    result = evaluate(accepted_decision(**{field: wrong_value}))

    assert result["can_commit"] is False
    assert result["reason_code"] == "CONTEXT_MISMATCH"


def test_expired_consent():
    result = evaluate(
        context=trusted_context(
            consent_recorded_at=NOW - timedelta(hours=2),
        )
    )

    assert result["can_commit"] is False
    assert result["reason_code"] == "CONSENT_EXPIRED"


def test_future_dated_consent():
    result = evaluate(
        context=trusted_context(
            consent_recorded_at=NOW + timedelta(minutes=10),
        )
    )

    assert result["can_commit"] is False
    assert result["reason_code"] == "CONSENT_IN_FUTURE"


def test_missing_dispatcher_identity():
    result = evaluate(context=trusted_context(dispatcher_id=None))

    assert result["can_commit"] is False


def test_missing_dispatcher_approval_timestamp():
    result = evaluate(context=trusted_context(dispatcher_approved_at=None))

    assert result["can_commit"] is False


def test_dispatcher_approval_before_driver_consent():
    result = evaluate(
        context=trusted_context(
            dispatcher_approved_at=NOW - timedelta(minutes=10),
        )
    )

    assert result["can_commit"] is False


def test_naive_consent_timestamp():
    result = evaluate(
        context=trusted_context(
            consent_recorded_at=datetime(2026, 11, 6, 12, 0),
        )
    )

    assert result["can_commit"] is False


def test_invalid_decision():
    result = AIRescueApprovalGate.evaluate(None)

    assert result["can_commit"] is False
    assert result["reason_code"] == "INVALID_DECISION"


def test_empty_assignment_identifier():
    result = evaluate(context=trusted_context(assignment_id=""))

    assert result["can_commit"] is False


def test_zero_consent_ttl():
    result = AIRescueApprovalGate.evaluate(
        accepted_decision(),
        context=trusted_context(),
        dispatcher_approved=True,
        now=NOW,
        consent_ttl=timedelta(0),
    )

    assert result["can_commit"] is False
