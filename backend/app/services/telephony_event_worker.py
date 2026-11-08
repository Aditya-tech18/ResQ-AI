"""Safe, provider-independent processing of queued telephony events.

This worker deliberately does not update rescue assignments, accept
driver consent, or call a telephony provider.

A later integration must connect lifecycle events to authenticated
provider call IDs and idempotent rescue workflow transitions.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.services.telephony_event_inbox import (
    InboxJob,
    TelephonyEventInbox,
)

logger = logging.getLogger(__name__)


class EventProcessingError(RuntimeError):
    """A telephony event could not be safely processed."""


class PermanentEventError(EventProcessingError):
    """An event cannot be handled without code or configuration changes."""


class RetryableEventError(EventProcessingError):
    """A temporary processing failure."""


class EventHandler(Protocol):
    def __call__(self, job: InboxJob) -> None: ...


@dataclass(frozen=True, slots=True)
class WorkerResult:
    event_id: str | None
    outcome: str
    attempt_count: int = 0
    error_type: str | None = None


class TelephonyEventWorker:
    """Lease and process telephony events with explicit handlers.

    Handlers MUST be idempotent because a worker can crash after
    performing a side effect but before marking an event completed.

    This worker does not renew leases. Keep handlers shorter than
    the configured lease duration, or add renewal before using
    long-running network operations.
    """

    SAFE_LIFECYCLE_EVENTS = frozenset(
        {
            "call.queued",
            "call.started",
            "call.ringing",
            "call.answered",
            "call.completed",
            "call.failed",
            "call.busy",
            "call.no_answer",
        }
    )

    CONSENT_EVENTS = frozenset(
        {
            "driver.accepted",
            "driver.declined",
            "driver.consent",
            "driver.confirmed",
        }
    )

    def __init__(
        self,
        inbox: TelephonyEventInbox,
        *,
        handlers: Mapping[str, EventHandler] | None = None,
        retry_delay_seconds: int = 30,
    ) -> None:
        if not isinstance(inbox, TelephonyEventInbox):
            raise TypeError("A TelephonyEventInbox is required")

        if type(retry_delay_seconds) is not int or retry_delay_seconds < 0:
            raise ValueError("Invalid retry delay")

        supplied = dict(handlers or {})

        if not all(callable(handler) for handler in supplied.values()):
            raise TypeError("Every event handler must be callable")

        forbidden = set(supplied) - self.SAFE_LIFECYCLE_EVENTS

        if forbidden:
            raise ValueError(
                "Unsupported or consent-related event handlers: " + ", ".join(sorted(forbidden))
            )

        self.inbox = inbox
        self.handlers = supplied
        self.retry_delay_seconds = retry_delay_seconds

    @staticmethod
    def _validate_job(job: InboxJob) -> None:
        if not job.event_id or not job.provider_call_id:
            raise PermanentEventError("Event or provider call ID is missing")

        if not isinstance(job.payload, Mapping):
            raise PermanentEventError("Event payload must be a mapping")

        if job.payload.get("event_id") != job.event_id:
            raise PermanentEventError("Event ID does not match stored payload")

        if job.payload.get("event_type") != job.event_type:
            raise PermanentEventError("Event type does not match stored payload")

        if job.payload.get("provider_call_id") != job.provider_call_id:
            raise PermanentEventError("Provider call ID does not match stored payload")

    def process_one(self) -> WorkerResult:
        """Process at most one event.

        Unknown and consent-related events remain pending with a
        retry delay. They are NEVER interpreted as driver consent.
        """
        job = self.inbox.claim_next()

        if job is None:
            return WorkerResult(
                event_id=None,
                outcome="idle",
            )

        try:
            self._validate_job(job)

            if job.event_type in self.CONSENT_EVENTS:
                raise PermanentEventError(
                    "Driver consent requires a separate verified-consent processor"
                )

            if job.event_type not in self.SAFE_LIFECYCLE_EVENTS:
                raise PermanentEventError("Unsupported telephony event type")

            handler = self.handlers.get(job.event_type)

            if handler is None:
                raise PermanentEventError("No lifecycle handler configured")

            handler(job)

        except PermanentEventError:
            self._retry(
                job,
                "Event requires manual review or configuration",
            )
            return WorkerResult(
                event_id=job.event_id,
                outcome="blocked",
                attempt_count=job.attempt_count,
                error_type="permanent",
            )

        except Exception:
            logger.exception(
                "Telephony event processing failed: %s",
                job.event_id,
            )

            self._retry(
                job,
                "Lifecycle handler failed",
            )

            return WorkerResult(
                event_id=job.event_id,
                outcome="retry_scheduled",
                attempt_count=job.attempt_count,
                error_type="retryable",
            )

        self.inbox.complete(
            job.event_id,
            job.lease_token,
        )

        return WorkerResult(
            event_id=job.event_id,
            outcome="completed",
            attempt_count=job.attempt_count,
        )

    def _retry(
        self,
        job: InboxJob,
        message: str,
    ) -> None:
        self.inbox.retry(
            job.event_id,
            job.lease_token,
            error=message,
            delay_seconds=self.retry_delay_seconds,
        )

    def process_batch(
        self,
        *,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Process a bounded number of available events."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Batch limit must be 1..1000")

        results: list[WorkerResult] = []

        for _ in range(limit):
            result = self.process_one()

            if result.outcome == "idle":
                break

            results.append(result)

        counts: dict[str, int] = {}

        for result in results:
            counts[result.outcome] = counts.get(result.outcome, 0) + 1

        return {
            "processed": len(results),
            "outcomes": counts,
            "events": [
                {
                    "event_id": result.event_id,
                    "outcome": result.outcome,
                    "attempt_count": result.attempt_count,
                }
                for result in results
            ],
        }
