"""Durable inbox for authenticated telephony events.

Authentication must happen before an event is submitted here.

This inbox supports:
- Durable SQLite storage
- Idempotent event submission
- Atomic worker claims
- Leased processing
- Retry after worker failure
- Terminal completion
- Event payload consistency checks

The inbox does not independently authenticate providers or drivers.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.telephony_webhook_security import (
    AuthenticatedTelephonyEvent,
)


class TelephonyInboxError(RuntimeError):
    """Inbox storage or state transition failed."""


@dataclass(frozen=True, slots=True)
class InboxJob:
    event_id: str
    event_type: str
    provider_call_id: str
    payload: Mapping[str, Any]
    attempt_count: int
    lease_token: str


class TelephonyEventInbox:
    """SQLite-backed, lease-based event processing inbox."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        lease_seconds: int = 60,
    ) -> None:
        self.db_path = Path(db_path)

        if type(lease_seconds) is not int or lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")

        if not self.db_path.parent.is_dir():
            raise TelephonyInboxError("Inbox database directory does not exist")

        self.lease_seconds = lease_seconds
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(
            self.db_path,
            timeout=15,
            isolation_level=None,
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 15000")
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS telephony_inbox (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    provider_call_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    lease_token TEXT,
                    lease_expires_at INTEGER,
                    next_attempt_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    last_error TEXT,
                    CHECK (
                        status IN (
                            'pending',
                            'processing',
                            'completed'
                        )
                    )
                )
                """
            )

            db.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_telephony_inbox_ready
                ON telephony_inbox (
                    status,
                    next_attempt_at,
                    lease_expires_at
                )
                """
            )

    @staticmethod
    def _now() -> int:
        return int(datetime.now(UTC).timestamp())

    @staticmethod
    def _serialize(
        event: AuthenticatedTelephonyEvent,
    ) -> tuple[str, str]:
        try:
            payload_json = json.dumps(
                dict(event.payload),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise TelephonyInboxError("Event payload is not JSON serializable") from exc

        digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

        return payload_json, digest

    def submit(
        self,
        event: AuthenticatedTelephonyEvent,
    ) -> bool:
        """Persist an authenticated event.

        Returns True for a new event, False for an identical
        previously stored event.

        Reusing an event ID with different content is rejected.
        """
        if not isinstance(event, AuthenticatedTelephonyEvent):
            raise TelephonyInboxError("AuthenticatedTelephonyEvent is required")

        payload_json, digest = self._serialize(event)
        now = self._now()

        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")

                existing = db.execute(
                    """
                    SELECT event_type, provider_call_id, payload_hash
                    FROM telephony_inbox
                    WHERE event_id = ?
                    """,
                    (event.event_id,),
                ).fetchone()

                if existing is not None:
                    if (
                        existing["event_type"] != event.event_type
                        or existing["provider_call_id"] != event.provider_call_id
                        or existing["payload_hash"] != digest
                    ):
                        raise TelephonyInboxError("Conflicting event ID reuse")

                    return False

                db.execute(
                    """
                    INSERT INTO telephony_inbox (
                        event_id,
                        event_type,
                        provider_call_id,
                        payload_json,
                        payload_hash,
                        status,
                        next_attempt_at,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.event_type,
                        event.provider_call_id,
                        payload_json,
                        digest,
                        now,
                        now,
                        now,
                    ),
                )

                return True

        except sqlite3.Error as exc:
            raise TelephonyInboxError("Unable to persist telephony event") from exc

    def claim_next(self) -> InboxJob | None:
        """Atomically lease one ready event for processing."""
        now = self._now()
        token = uuid.uuid4().hex

        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")

                row = db.execute(
                    """
                    SELECT *
                    FROM telephony_inbox
                    WHERE (
                        status = 'pending'
                        AND next_attempt_at <= ?
                    )
                    OR (
                        status = 'processing'
                        AND lease_expires_at <= ?
                    )
                    ORDER BY created_at, event_id
                    LIMIT 1
                    """,
                    (now, now),
                ).fetchone()

                if row is None:
                    return None

                db.execute(
                    """
                    UPDATE telephony_inbox
                    SET status = 'processing',
                        lease_token = ?,
                        lease_expires_at = ?,
                        attempt_count = attempt_count + 1,
                        updated_at = ?
                    WHERE event_id = ?
                    """,
                    (
                        token,
                        now + self.lease_seconds,
                        now,
                        row["event_id"],
                    ),
                )

                return InboxJob(
                    event_id=row["event_id"],
                    event_type=row["event_type"],
                    provider_call_id=row["provider_call_id"],
                    payload=json.loads(row["payload_json"]),
                    attempt_count=row["attempt_count"] + 1,
                    lease_token=token,
                )

        except (sqlite3.Error, ValueError) as exc:
            raise TelephonyInboxError("Unable to claim telephony event") from exc

    def complete(
        self,
        event_id: str,
        lease_token: str,
    ) -> None:
        """Mark processing complete for the current lease only."""
        now = self._now()

        try:
            with self._connect() as db:
                cursor = db.execute(
                    """
                    UPDATE telephony_inbox
                    SET status = 'completed',
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?,
                        last_error = NULL
                    WHERE event_id = ?
                      AND lease_token = ?
                      AND status = 'processing'
                      AND lease_expires_at > ?
                    """,
                    (now, event_id, lease_token, now),
                )

                if cursor.rowcount != 1:
                    raise TelephonyInboxError("Invalid or expired processing lease")

        except sqlite3.Error as exc:
            raise TelephonyInboxError("Unable to complete event") from exc

    def retry(
        self,
        event_id: str,
        lease_token: str,
        *,
        error: str,
        delay_seconds: int = 30,
    ) -> None:
        """Return a failed event to the pending queue."""
        if type(delay_seconds) is not int or delay_seconds < 0:
            raise ValueError("Invalid retry delay")

        now = self._now()

        try:
            with self._connect() as db:
                cursor = db.execute(
                    """
                    UPDATE telephony_inbox
                    SET status = 'pending',
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        next_attempt_at = ?,
                        updated_at = ?,
                        last_error = ?
                    WHERE event_id = ?
                      AND lease_token = ?
                      AND status = 'processing'
                      AND lease_expires_at > ?
                    """,
                    (
                        now + delay_seconds,
                        now,
                        str(error)[:1000],
                        event_id,
                        lease_token,
                        now,
                    ),
                )

                if cursor.rowcount != 1:
                    raise TelephonyInboxError("Invalid or expired processing lease")

        except sqlite3.Error as exc:
            raise TelephonyInboxError("Unable to schedule event retry") from exc

    def get_status(self, event_id: str) -> dict[str, Any] | None:
        """Return persisted event processing status."""
        try:
            with self._connect() as db:
                row = db.execute(
                    """
                    SELECT
                        event_id,
                        status,
                        attempt_count,
                        next_attempt_at,
                        last_error
                    FROM telephony_inbox
                    WHERE event_id = ?
                    """,
                    (event_id,),
                ).fetchone()

                return dict(row) if row is not None else None

        except sqlite3.Error as exc:
            raise TelephonyInboxError("Unable to read event status") from exc
