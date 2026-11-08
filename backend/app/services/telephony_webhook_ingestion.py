"""Authenticated, durable ingestion of telephony lifecycle events.

Flow:
    HTTP body + timestamp + signature
        -> validate request age
        -> verify HMAC-SHA256
        -> validate event structure
        -> atomically insert into durable inbox
        -> acknowledge event

Security note:
    The signing format here is application-defined:
        HMAC_SHA256(secret, timestamp + "." + raw_body)

    It is NOT a verified Gnani-specific webhook protocol.
    A provider adapter must implement the provider's documented
    signature format before connecting live webhooks.

The inbox is the authoritative duplicate-event store. We do not
claim a replay ID in a separate database before persisting the event.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.services.telephony_event_inbox import (
    TelephonyEventInbox,
    TelephonyInboxError,
)
from app.services.telephony_webhook_security import (
    AuthenticatedTelephonyEvent,
)

_EVENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_CALL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SIGNATURE_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_TIMESTAMP_PATTERN = re.compile(r"^[0-9]{1,12}$")


class WebhookIngestionError(ValueError):
    """Invalid, unauthenticated, or unpersistable webhook."""


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Result returned only after durable storage is confirmed."""

    event_id: str
    event_type: str
    provider_call_id: str
    outcome: str
    accepted: bool


class TelephonyWebhookIngestionService:
    """Validate a signed webhook and store it before acknowledgment."""

    def __init__(
        self,
        *,
        secret: str | bytes,
        inbox: TelephonyEventInbox,
        max_age_seconds: int = 300,
        max_body_bytes: int = 262_144,
    ) -> None:
        if isinstance(secret, str):
            secret_bytes = secret.encode("utf-8")
        elif isinstance(secret, bytes):
            secret_bytes = secret
        else:
            raise ValueError("Webhook secret must be text or bytes")

        if len(secret_bytes) < 32:
            raise ValueError("Webhook secret must contain at least 32 bytes")

        if not isinstance(inbox, TelephonyEventInbox):
            raise TypeError("A durable inbox is required")

        if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 3600:
            raise ValueError("Invalid webhook age limit")

        if type(max_body_bytes) is not int or not 1024 <= max_body_bytes <= 1_048_576:
            raise ValueError("Invalid webhook body size limit")

        self._secret = secret_bytes
        self._inbox = inbox
        self._max_age_seconds = max_age_seconds
        self._max_body_bytes = max_body_bytes

    def ingest(
        self,
        *,
        body: bytes,
        timestamp: str,
        signature: str,
        now: datetime | None = None,
    ) -> IngestionResult:
        """Authenticate, validate, and durably store one event.

        An identical duplicate is acknowledged without re-enqueueing.
        Conflicting reuse of an event ID is rejected.
        """

        current_time = now or datetime.now(UTC)

        if current_time.tzinfo is None or current_time.utcoffset() is None:
            raise WebhookIngestionError("Current time must include timezone information")

        if not isinstance(body, bytes):
            raise WebhookIngestionError("Webhook body must be raw bytes")

        if not body or len(body) > self._max_body_bytes:
            raise WebhookIngestionError("Webhook body is empty or too large")

        if not isinstance(timestamp, str) or not _TIMESTAMP_PATTERN.fullmatch(timestamp):
            raise WebhookIngestionError("Invalid webhook timestamp")

        request_time = int(timestamp)
        now_seconds = current_time.timestamp()

        if abs(now_seconds - request_time) > self._max_age_seconds:
            raise WebhookIngestionError("Webhook timestamp is expired or too far ahead")

        if not isinstance(signature, str) or not _SIGNATURE_PATTERN.fullmatch(signature):
            raise WebhookIngestionError("Invalid webhook signature format")

        message = timestamp.encode("ascii") + b"." + body

        expected_signature = hmac.new(
            self._secret,
            message,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(
            expected_signature,
            signature.lower(),
        ):
            raise WebhookIngestionError("Webhook authentication failed")

        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebhookIngestionError("Webhook body must contain valid JSON") from exc

        if not isinstance(payload, dict):
            raise WebhookIngestionError("Webhook JSON must be an object")

        event_id = payload.get("event_id")
        event_type = payload.get("event_type")
        provider_call_id = payload.get("provider_call_id")

        self._validate_identifier(
            event_id,
            _EVENT_ID_PATTERN,
            "event_id",
        )
        self._validate_identifier(
            event_type,
            _EVENT_TYPE_PATTERN,
            "event_type",
        )
        self._validate_identifier(
            provider_call_id,
            _CALL_ID_PATTERN,
            "provider_call_id",
        )

        occurred_at = self._parse_event_time(
            payload.get("occurred_at"),
            current_time,
        )

        # Reject non-standard JSON values such as NaN and Infinity,
        # including values nested inside lists or dictionaries.
        self._validate_finite_json(payload)

        authenticated_event = AuthenticatedTelephonyEvent(
            event_id=event_id,
            event_type=event_type,
            provider_call_id=provider_call_id,
            occurred_at=occurred_at,
            payload=payload,
        )

        try:
            inserted = self._inbox.submit(authenticated_event)
        except TelephonyInboxError as exc:
            # Never acknowledge successful ingestion when the
            # database could not safely persist the event.
            raise WebhookIngestionError("Unable to persist authenticated webhook") from exc

        return IngestionResult(
            event_id=event_id,
            event_type=event_type,
            provider_call_id=provider_call_id,
            outcome="stored" if inserted else "duplicate",
            accepted=True,
        )

    @staticmethod
    def _validate_identifier(
        value: Any,
        pattern: re.Pattern[str],
        field_name: str,
    ) -> None:
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise WebhookIngestionError(f"Invalid webhook field: {field_name}")

    def _parse_event_time(
        self,
        value: Any,
        now: datetime,
    ) -> datetime:
        if not isinstance(value, str):
            raise WebhookIngestionError("Missing event occurrence timestamp")

        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise WebhookIngestionError("Invalid event occurrence timestamp") from exc

        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise WebhookIngestionError("Event timestamp must include timezone")

        if abs((now - parsed).total_seconds()) > self._max_age_seconds:
            raise WebhookIngestionError("Event occurrence time is outside allowed window")

        return parsed.astimezone(UTC)

    @staticmethod
    def _validate_finite_json(value: Any) -> None:
        if isinstance(value, float):
            if value != value or value in (
                float("inf"),
                float("-inf"),
            ):
                raise WebhookIngestionError("Non-finite JSON number is not allowed")
        elif isinstance(value, dict):
            for nested in value.values():
                TelephonyWebhookIngestionService._validate_finite_json(nested)
        elif isinstance(value, list):
            for nested in value:
                TelephonyWebhookIngestionService._validate_finite_json(nested)
