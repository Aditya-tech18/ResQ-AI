"""Provider-independent authentication for telephony webhook events.

This module defines an application-owned HMAC-SHA256 webhook protocol.
It is not an implementation of any particular provider's webhook format.

Security properties:
- Raw request bytes are authenticated before JSON parsing.
- HMAC signatures use constant-time comparison.
- Timestamps are checked against an explicit acceptance window.
- Duplicate event IDs can be rejected by a persistent replay store.
- The verifier never trusts identity or consent claims from an LLM.

A production provider adapter must use the provider's documented
signature algorithm and must supply a persistent replay store.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class TelephonyWebhookError(ValueError):
    """A telephony webhook failed authentication or validation."""


@dataclass(frozen=True, slots=True)
class AuthenticatedTelephonyEvent:
    event_id: str
    event_type: str
    provider_call_id: str
    occurred_at: datetime
    payload: Mapping[str, Any]


class SQLiteWebhookReplayStore:
    """Persistent replay protection shared across application workers.

    Use a dedicated database or carefully managed application database.
    Expired event IDs may be pruned after the maximum accepted event age.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

        if not self.db_path.parent.exists():
            raise TelephonyWebhookError("Replay-store directory does not exist")

        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.db_path,
            timeout=15,
            isolation_level=None,
        )
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS telephony_webhook_events (
                    event_id TEXT PRIMARY KEY,
                    received_at INTEGER NOT NULL
                )
                """
            )

    def claim(self, event_id: str, received_at: int) -> bool:
        """Atomically claim an event ID once across processes."""
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")

                cursor = db.execute(
                    """
                    INSERT OR IGNORE INTO telephony_webhook_events
                        (event_id, received_at)
                    VALUES (?, ?)
                    """,
                    (event_id, received_at),
                )

                claimed = cursor.rowcount == 1
                db.commit()
                return claimed

        except sqlite3.Error as exc:
            raise TelephonyWebhookError("Replay protection storage is unavailable") from exc

    def prune(self, before_timestamp: int) -> int:
        """Delete old event IDs after the replay retention window."""
        try:
            with self._connect() as db:
                cursor = db.execute(
                    """
                    DELETE FROM telephony_webhook_events
                    WHERE received_at < ?
                    """,
                    (before_timestamp,),
                )
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise TelephonyWebhookError("Replay-store cleanup failed") from exc


class TelephonyWebhookVerifier:
    """Verify an application-owned HMAC-signed telephony event."""

    SIGNATURE_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")
    EVENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

    DEFAULT_MAX_AGE_SECONDS = 300
    DEFAULT_MAX_BODY_BYTES = 256 * 1024

    def __init__(
        self,
        *,
        secret: str | bytes,
        replay_store: SQLiteWebhookReplayStore,
        max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        if isinstance(secret, str):
            secret_bytes = secret.encode("utf-8")
        elif isinstance(secret, bytes):
            secret_bytes = secret
        else:
            raise TelephonyWebhookError("Webhook secret must be text or bytes")

        if len(secret_bytes) < 32:
            raise TelephonyWebhookError("Webhook secret must contain at least 32 bytes")

        if not isinstance(replay_store, SQLiteWebhookReplayStore):
            raise TelephonyWebhookError("A persistent replay store is required")

        if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 3600:
            raise TelephonyWebhookError("Invalid webhook age window")

        if type(max_body_bytes) is not int or not 1024 <= max_body_bytes <= 1024 * 1024:
            raise TelephonyWebhookError("Invalid webhook payload size limit")

        self._secret = secret_bytes
        self._replay_store = replay_store
        self._max_age_seconds = max_age_seconds
        self._max_body_bytes = max_body_bytes

    @staticmethod
    def _parse_timestamp(value: str) -> int:
        if (
            not isinstance(value, str)
            or not value.isascii()
            or not value.isdecimal()
            or len(value) > 12
        ):
            raise TelephonyWebhookError("Invalid webhook timestamp")

        return int(value)

    def _verify_signature(
        self,
        *,
        body: bytes,
        timestamp: str,
        signature: str,
    ) -> None:
        if not isinstance(signature, str):
            raise TelephonyWebhookError("Missing webhook signature")

        if not self.SIGNATURE_PATTERN.fullmatch(signature):
            raise TelephonyWebhookError("Invalid webhook signature format")

        signed_payload = timestamp.encode("ascii") + b"." + body

        expected = hmac.new(
            self._secret,
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(
            expected,
            signature.lower(),
        ):
            raise TelephonyWebhookError("Webhook signature verification failed")

    def verify(
        self,
        *,
        body: bytes,
        timestamp: str,
        signature: str,
        now: datetime | None = None,
    ) -> AuthenticatedTelephonyEvent:
        """Authenticate, validate, and claim one webhook event.

        Wire format:
            signature = hex(HMAC_SHA256(secret, timestamp + "." + raw_body))

        The event JSON must include:
            event_id, event_type, provider_call_id, occurred_at

        occurred_at must be an ISO-8601 timezone-aware timestamp.
        """
        if not isinstance(body, bytes):
            raise TelephonyWebhookError("Webhook body must be raw bytes")

        if len(body) > self._max_body_bytes:
            raise TelephonyWebhookError("Webhook payload exceeds size limit")

        event_timestamp = self._parse_timestamp(timestamp)

        current_time = now or datetime.now(UTC)

        if current_time.tzinfo is None:
            raise TelephonyWebhookError("Current time must be timezone-aware")

        current_timestamp = int(current_time.timestamp())

        if abs(current_timestamp - event_timestamp) > self._max_age_seconds:
            raise TelephonyWebhookError("Webhook timestamp is outside the allowed window")

        self._verify_signature(
            body=body,
            timestamp=timestamp,
            signature=signature,
        )

        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TelephonyWebhookError("Webhook body must contain valid JSON") from exc

        if not isinstance(payload, dict):
            raise TelephonyWebhookError("Webhook JSON must be an object")

        event_id = payload.get("event_id")
        event_type = payload.get("event_type")
        provider_call_id = payload.get("provider_call_id")
        occurred_at = payload.get("occurred_at")

        if not isinstance(event_id, str) or not self.EVENT_ID_PATTERN.fullmatch(event_id):
            raise TelephonyWebhookError("Invalid webhook event ID")

        if not isinstance(event_type, str) or not 1 <= len(event_type) <= 100:
            raise TelephonyWebhookError("Invalid webhook event type")

        if not isinstance(provider_call_id, str) or not 1 <= len(provider_call_id) <= 256:
            raise TelephonyWebhookError("Invalid provider call ID")

        if not isinstance(occurred_at, str):
            raise TelephonyWebhookError("Missing event occurrence timestamp")

        try:
            event_time = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise TelephonyWebhookError("Invalid event occurrence timestamp") from exc

        if event_time.tzinfo is None:
            raise TelephonyWebhookError("Event occurrence timestamp must have a timezone")

        if abs((current_time - event_time).total_seconds()) > self._max_age_seconds:
            raise TelephonyWebhookError("Event occurrence time is outside the allowed window")

        if not self._replay_store.claim(
            event_id,
            current_timestamp,
        ):
            raise TelephonyWebhookError("Duplicate webhook event")

        return AuthenticatedTelephonyEvent(
            event_id=event_id,
            event_type=event_type,
            provider_call_id=provider_call_id,
            occurred_at=event_time.astimezone(UTC),
            payload=payload,
        )
