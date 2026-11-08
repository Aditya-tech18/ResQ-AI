"""DispatchResolve AI: persistent emergency rescue workflow.

A standalone SQLite-backed workflow for the synthetic Vizag demo.
All mutations are transactional. No external calls are performed.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.services.vizag_dataset_service import (
    VizagDatasetService,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "vizag_rescue.sqlite3"

LANGUAGES = {"hi", "te"}
TERMINAL_STATES = {"completed", "cancelled"}


class RescueWorkflowError(ValueError):
    """Invalid business transition or missing rescue entity."""


@dataclass(frozen=True)
class RescueEvent:
    event_id: str
    case_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


class EmergencyRescueWorkflow:
    """Transaction-safe orchestration for driver rescue cases."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB,
        dataset: VizagDatasetService | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.dataset = dataset or VizagDatasetService()
        self._initialize_database()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.db_path,
            timeout=15,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")

        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_database(self) -> None:
        with self.transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS rescue_cases (
                    case_id TEXT PRIMARY KEY,
                    merchant_id TEXT NOT NULL,
                    failed_driver_id TEXT NOT NULL,
                    emergency_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    breakdown_latitude REAL NOT NULL,
                    breakdown_longitude REAL NOT NULL,
                    reported_language TEXT NOT NULL,
                    reported_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    dispatcher_approved_at TEXT,
                    dispatcher_id TEXT,
                    version INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS rescue_assignments (
                    assignment_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    shipment_id TEXT NOT NULL,
                    replacement_driver_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    call_language TEXT NOT NULL,
                    pickup_distance_km REAL NOT NULL,
                    route_deviation_km REAL NOT NULL,
                    accepted_at TEXT,
                    handover_verified_at TEXT,
                    handover_verified_by TEXT,
                    otp_hash TEXT,
                    otp_expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(case_id)
                        REFERENCES rescue_cases(case_id),
                    UNIQUE(case_id, shipment_id)
                );

                CREATE TABLE IF NOT EXISTS rescue_calls (
                    call_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    assignment_id TEXT NOT NULL,
                    driver_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_language TEXT NOT NULL,
                    provider_call_id TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(case_id)
                        REFERENCES rescue_cases(case_id),
                    FOREIGN KEY(assignment_id)
                        REFERENCES rescue_assignments(assignment_id)
                );

                CREATE TABLE IF NOT EXISTS rescue_events (
                    event_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(case_id)
                        REFERENCES rescue_cases(case_id)
                );

                CREATE INDEX IF NOT EXISTS ix_rescue_case_driver
                    ON rescue_cases(failed_driver_id, status);

                CREATE INDEX IF NOT EXISTS ix_rescue_assignment_driver
                    ON rescue_assignments(replacement_driver_id, status);

                CREATE INDEX IF NOT EXISTS ix_rescue_events_case
                    ON rescue_events(case_id, created_at);
                """
            )

    @staticmethod
    def _event(
        db: sqlite3.Connection,
        case_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        db.execute(
            """
            INSERT INTO rescue_events (
                event_id, case_id, event_type,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                new_id("EVT"),
                case_id,
                event_type,
                json.dumps(payload, ensure_ascii=False),
                utc_now(),
            ),
        )

    @staticmethod
    def _get_case(
        db: sqlite3.Connection,
        case_id: str,
    ) -> sqlite3.Row:
        row = db.execute(
            "SELECT * FROM rescue_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()

        if row is None:
            raise RescueWorkflowError(f"Rescue case not found: {case_id}")

        return row

    @staticmethod
    def _get_assignment(
        db: sqlite3.Connection,
        assignment_id: str,
    ) -> sqlite3.Row:
        row = db.execute(
            """
            SELECT * FROM rescue_assignments
            WHERE assignment_id = ?
            """,
            (assignment_id,),
        ).fetchone()

        if row is None:
            raise RescueWorkflowError(f"Assignment not found: {assignment_id}")

        return row

    def create_case(
        self,
        failed_driver_id: str,
        emergency_type: str = "vehicle_breakdown",
        reported_language: str = "hi",
        simulated_time: datetime | None = None,
    ) -> dict[str, Any]:
        if reported_language not in LANGUAGES:
            raise RescueWorkflowError("Unsupported language")

        driver = self.dataset.get_driver(failed_driver_id)

        # Fixed historical GPS timestamps in the synthetic dataset.
        reference_time = simulated_time or driver.gps_last_updated_at + timedelta(minutes=5)

        plan = self.dataset.create_rescue_plan(
            failed_driver_id=failed_driver_id,
            breakdown_location=driver.position,
            reference_time=reference_time,
        )

        if not plan.get("pending_parcel_count"):
            raise RescueWorkflowError("Driver has no pending shipments")

        case_id = new_id("RESCUE")
        now = utc_now()

        with self.transaction() as db:
            active = db.execute(
                """
                SELECT case_id FROM rescue_cases
                WHERE failed_driver_id = ?
                  AND merchant_id = ?
                  AND status NOT IN ('completed', 'cancelled')
                LIMIT 1
                """,
                (failed_driver_id, driver.merchant_id),
            ).fetchone()

            if active:
                raise RescueWorkflowError(f"Active rescue case already exists: {active['case_id']}")

            db.execute(
                """
                INSERT INTO rescue_cases (
                    case_id, merchant_id, failed_driver_id,
                    emergency_type, status,
                    breakdown_latitude, breakdown_longitude,
                    reported_language, reported_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    driver.merchant_id,
                    failed_driver_id,
                    emergency_type,
                    "matching",
                    driver.position.latitude,
                    driver.position.longitude,
                    reported_language,
                    now,
                    now,
                ),
            )

            for proposed in plan["assignments"]:
                db.execute(
                    """
                    INSERT INTO rescue_assignments (
                        assignment_id, case_id, shipment_id,
                        replacement_driver_id, status,
                        call_language, pickup_distance_km,
                        route_deviation_km, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("ASG"),
                        case_id,
                        proposed["shipment_id"],
                        proposed["replacement_driver_id"],
                        "proposed",
                        "hi",
                        proposed["pickup_distance_km"],
                        proposed["route_deviation_km"],
                        now,
                        now,
                    ),
                )

            self._event(
                db,
                case_id,
                "emergency_reported",
                {
                    "failed_driver_id": failed_driver_id,
                    "emergency_type": emergency_type,
                    "language": reported_language,
                    "pending_parcel_count": plan["pending_parcel_count"],
                },
            )

            self._event(
                db,
                case_id,
                "rescue_plan_created",
                {
                    "assignments": plan["assignments"],
                    "unassigned": plan["unassigned_shipment_ids"],
                    "committed": False,
                },
            )

        return self.get_case(case_id)

    def prepare_outbound_calls(
        self,
        case_id: str,
    ) -> list[dict[str, Any]]:
        """Queue call records; no telephony is invoked."""

        with self.transaction() as db:
            case = self._get_case(db, case_id)

            if case["status"] in TERMINAL_STATES:
                raise RescueWorkflowError("Cannot call drivers for a closed case")

            assignments = db.execute(
                """
                SELECT * FROM rescue_assignments
                WHERE case_id = ? AND status = 'proposed'
                ORDER BY shipment_id
                """,
                (case_id,),
            ).fetchall()

            created = []

            for assignment in assignments:
                call_id = new_id("CALL")
                now = utc_now()

                db.execute(
                    """
                    INSERT INTO rescue_calls (
                        call_id, case_id, assignment_id,
                        driver_id, status,
                        current_language, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        call_id,
                        case_id,
                        assignment["assignment_id"],
                        assignment["replacement_driver_id"],
                        "queued",
                        "hi",
                        now,
                    ),
                )

                db.execute(
                    """
                    UPDATE rescue_assignments
                    SET status = 'call_queued', updated_at = ?
                    WHERE assignment_id = ?
                    """,
                    (now, assignment["assignment_id"]),
                )

                created.append(
                    {
                        "call_id": call_id,
                        "assignment_id": assignment["assignment_id"],
                        "driver_id": assignment["replacement_driver_id"],
                        "initial_language": "hi",
                        "status": "queued",
                    }
                )

            if created:
                db.execute(
                    """
                    UPDATE rescue_cases
                    SET status = 'calling',
                        updated_at = ?,
                        version = version + 1
                    WHERE case_id = ?
                    """,
                    (utc_now(), case_id),
                )

                self._event(
                    db,
                    case_id,
                    "outbound_calls_queued",
                    {"calls": created},
                )

        return created

    def switch_call_language(
        self,
        call_id: str,
        detected_language: str,
    ) -> dict[str, Any]:
        if detected_language not in LANGUAGES:
            raise RescueWorkflowError("Only Hindi and Telugu are supported")

        with self.transaction() as db:
            call = db.execute(
                "SELECT * FROM rescue_calls WHERE call_id = ?",
                (call_id,),
            ).fetchone()

            if call is None:
                raise RescueWorkflowError("Call not found")

            if call["status"] not in {"queued", "in_progress"}:
                raise RescueWorkflowError("Language cannot change after call closure")

            old_language = call["current_language"]

            db.execute(
                """
                UPDATE rescue_calls
                SET current_language = ?
                WHERE call_id = ?
                """,
                (detected_language, call_id),
            )

            db.execute(
                """
                UPDATE rescue_assignments
                SET call_language = ?, updated_at = ?
                WHERE assignment_id = ?
                """,
                (
                    detected_language,
                    utc_now(),
                    call["assignment_id"],
                ),
            )

            self._event(
                db,
                call["case_id"],
                "call_language_changed",
                {
                    "call_id": call_id,
                    "from": old_language,
                    "to": detected_language,
                },
            )

        return {
            "call_id": call_id,
            "previous_language": old_language,
            "current_language": detected_language,
        }

    def record_driver_response(
        self,
        assignment_id: str,
        accepted: bool,
    ) -> dict[str, Any]:
        """Reject legacy, unauthenticated driver responses.

        Driver consent must be recorded using the authenticated
        VerifiedDriverConsentService, which validates the provider
        call identifier, driver identity, case relationships,
        call state, and explicit confirmation before committing.
        """
        raise RescueWorkflowError(
            "Legacy driver-response recording is disabled. "
            "Use VerifiedDriverConsentService with an authenticated "
            "provider event and verified driver identity."
        )

    def _simulate_driver_response_for_demo(
        self,
        assignment_id: str,
        accepted: bool,
    ) -> dict[str, Any]:
        """Simulate a response; never expose through an API route.

        This private helper exists only for the standalone demo.
        It must not be used for production consent recording.
        """
        with self.transaction() as db:
            assignment = self._get_assignment(db, assignment_id)

            if assignment["status"] != "call_queued":
                raise RescueWorkflowError("Driver response requires a queued call")

            status = "accepted" if accepted else "declined"
            now = utc_now()

            db.execute(
                """
                UPDATE rescue_assignments
                SET status = ?,
                    accepted_at = ?,
                    updated_at = ?
                WHERE assignment_id = ?
                """,
                (
                    status,
                    now if accepted else None,
                    now,
                    assignment_id,
                ),
            )

            db.execute(
                """
                UPDATE rescue_calls
                SET status = 'completed',
                    ended_at = ?
                WHERE assignment_id = ?
                  AND status = 'queued'
                """,
                (now, assignment_id),
            )

            self._event(
                db,
                assignment["case_id"],
                "driver_response_recorded",
                {
                    "assignment_id": assignment_id,
                    "driver_id": assignment["replacement_driver_id"],
                    "accepted": accepted,
                },
            )

        return {
            "assignment_id": assignment_id,
            "status": status,
        }

    def approve_case(
        self,
        case_id: str,
        dispatcher_id: str,
    ) -> dict[str, Any]:
        if not dispatcher_id.strip():
            raise RescueWorkflowError("Dispatcher identity is required")

        with self.transaction() as db:
            case = self._get_case(db, case_id)

            if case["status"] in TERMINAL_STATES:
                raise RescueWorkflowError("Closed case cannot be approved")

            assignments = db.execute(
                """
                SELECT status FROM rescue_assignments
                WHERE case_id = ?
                """,
                (case_id,),
            ).fetchall()

            if not assignments or any(row["status"] != "accepted" for row in assignments):
                raise RescueWorkflowError("All proposed assignments must be accepted")

            now = utc_now()

            db.execute(
                """
                UPDATE rescue_cases
                SET status = 'handover_pending',
                    dispatcher_id = ?,
                    dispatcher_approved_at = ?,
                    updated_at = ?,
                    version = version + 1
                WHERE case_id = ?
                """,
                (dispatcher_id, now, now, case_id),
            )

            self._event(
                db,
                case_id,
                "dispatcher_approved",
                {"dispatcher_id": dispatcher_id},
            )

        return self.get_case(case_id)

    def verify_handover(
        self,
        assignment_id: str,
        verified_by: str,
    ) -> dict[str, Any]:
        """Record a trusted operator's physical handover verification."""

        if not verified_by.strip():
            raise RescueWorkflowError("Verifier identity is required")

        with self.transaction() as db:
            assignment = self._get_assignment(db, assignment_id)
            case = self._get_case(db, assignment["case_id"])

            if case["status"] != "handover_pending":
                raise RescueWorkflowError("Dispatcher approval required before handover")

            if assignment["status"] != "accepted":
                raise RescueWorkflowError("Only accepted assignments can be verified")

            now = utc_now()

            db.execute(
                """
                UPDATE rescue_assignments
                SET status = 'handover_verified',
                    handover_verified_at = ?,
                    handover_verified_by = ?,
                    updated_at = ?
                WHERE assignment_id = ?
                """,
                (now, verified_by, now, assignment_id),
            )

            self._event(
                db,
                assignment["case_id"],
                "handover_verified",
                {
                    "assignment_id": assignment_id,
                    "verified_by": verified_by,
                },
            )

        return {
            "assignment_id": assignment_id,
            "status": "handover_verified",
        }

    def complete_case(self, case_id: str) -> dict[str, Any]:
        """Complete workflow; shipment ORM sync comes in a later phase."""

        with self.transaction() as db:
            case = self._get_case(db, case_id)

            if case["status"] != "handover_pending":
                raise RescueWorkflowError("Case must be awaiting handover")

            assignments = db.execute(
                """
                SELECT status FROM rescue_assignments
                WHERE case_id = ?
                """,
                (case_id,),
            ).fetchall()

            if not assignments or any(row["status"] != "handover_verified" for row in assignments):
                raise RescueWorkflowError("Every parcel requires verified handover")

            now = utc_now()

            db.execute(
                """
                UPDATE rescue_cases
                SET status = 'completed',
                    updated_at = ?,
                    version = version + 1
                WHERE case_id = ?
                """,
                (now, case_id),
            )

            self._event(
                db,
                case_id,
                "rescue_completed",
                {"shipment_database_synced": False},
            )

        return self.get_case(case_id)

    def get_case(self, case_id: str) -> dict[str, Any]:
        with self.transaction() as db:
            case = dict(self._get_case(db, case_id))

            assignments = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT * FROM rescue_assignments
                    WHERE case_id = ?
                    ORDER BY shipment_id
                    """,
                    (case_id,),
                ).fetchall()
            ]

            calls = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT * FROM rescue_calls
                    WHERE case_id = ?
                    ORDER BY created_at, call_id
                    """,
                    (case_id,),
                ).fetchall()
            ]

            events = [
                {
                    **dict(row),
                    "payload": json.loads(row["payload_json"]),
                }
                for row in db.execute(
                    """
                    SELECT * FROM rescue_events
                    WHERE case_id = ?
                    ORDER BY created_at, event_id
                    """,
                    (case_id,),
                ).fetchall()
            ]

        for event in events:
            event.pop("payload_json", None)

        return {
            "case": case,
            "assignments": assignments,
            "calls": calls,
            "events": events,
        }


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        workflow = EmergencyRescueWorkflow(db_path=Path(directory) / "demo.sqlite3")

        created = workflow.create_case("DRV-001")
        case_id = created["case"]["case_id"]

        print("CASE CREATED:", case_id)

        calls = workflow.prepare_outbound_calls(case_id)

        print("CALLS QUEUED:", len(calls))

        for call in calls:
            if call["driver_id"] == "DRV-002":
                print(
                    "LANGUAGE SWITCH:",
                    workflow.switch_call_language(call["call_id"], "te"),
                )

            # Demo-only simulation. This does not represent real consent.
            workflow._simulate_driver_response_for_demo(
                call["assignment_id"],
                accepted=True,
            )

        workflow.approve_case(
            case_id,
            dispatcher_id="DEMO-DISPATCHER",
        )

        for call in calls:
            workflow.verify_handover(
                call["assignment_id"],
                verified_by="DEMO-OPERATOR",
            )

        result = workflow.complete_case(case_id)

        print("FINAL STATUS:", result["case"]["status"])
        print("EVENTS:", len(result["events"]))
        print("NOTE: No real calls or shipment DB updates occurred.")
