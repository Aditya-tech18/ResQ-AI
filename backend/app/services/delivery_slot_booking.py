"""
DispatchResolve AI — Multilingual Delivery Slot Booking Engine.

Supports:
- Hindi and Telugu slot requests
- Explicit time interval detection
- Capacity-aware reservations
- Booking modification and cancellation
- SQLite persistence
- Merchant and shipment validation
- Transactional updates
- Event auditing

This service does not perform speech recognition,
outbound calls, or real-time route optimization.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.vizag_dataset_service import (
    RecordNotFoundError,
    VizagDatasetService,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "vizag_slots.sqlite3"

DEFAULT_SLOT_CAPACITY = 25

SUPPORTED_LANGUAGES = frozenset({"hi", "te"})

ACTIVE_BOOKING_STATUS = "confirmed"

SLOT_ALIASES = {
    "SLOT-01": {
        "hi": [
            "सुबह 6",
            "सुबह छह",
            "6 से 10",
            "6 am to 10 am",
            "6 बजे से 10 बजे",
        ],
        "te": [
            "ఉదయం ఆరు",
            "ఉదయం 6",
            "6 నుంచి 10",
            "ఉదయం ఆరు నుంచి పది",
        ],
    },
    "SLOT-02": {
        "hi": [
            "सुबह 10",
            "दोपहर 2 तक",
            "10 से 2",
            "10 am to 2 pm",
            "10 बजे से 2 बजे",
        ],
        "te": [
            "ఉదయం పది",
            "10 నుంచి 2",
            "పది నుంచి రెండు",
        ],
    },
    "SLOT-03": {
        "hi": [
            "दोपहर 2",
            "शाम 6",
            "2 से 6",
            "2 pm to 6 pm",
            "दो बजे से शाम छह बजे",
            "दोपहर दो बजे से शाम छह बजे",
        ],
        "te": [
            "మధ్యాహ్నం రెండు",
            "సాయంత్రం ఆరు",
            "2 నుంచి 6",
            "రెండు గంటల నుంచి సాయంత్రం ఆరు",
            "మధ్యాహ్నం రెండు గంటల నుంచి సాయంత్రం ఆరు",
        ],
    },
    "SLOT-04": {
        "hi": [
            "शाम 6",
            "रात 10",
            "6 से 10",
            "6 pm to 10 pm",
            "शाम छह से रात दस",
        ],
        "te": [
            "సాయంత్రం ఆరు",
            "రాత్రి పది",
            "6 నుంచి 10",
            "సాయంత్రం ఆరు నుంచి రాత్రి పది",
        ],
    },
    "SLOT-05": {
        "hi": [
            "रात 10 से 2",
            "10 pm to 2 am",
            "रात दस से दो",
        ],
        "te": [
            "రాత్రి పది నుంచి రెండు",
            "10 pm నుంచి 2 am",
        ],
    },
}


class SlotBookingError(ValueError):
    """Invalid slot operation."""


class SlotUnavailableError(SlotBookingError):
    """Requested delivery slot has reached capacity."""


class SlotUnderstandingError(SlotBookingError):
    """The customer's utterance does not identify one unique slot."""


@dataclass(frozen=True, slots=True)
class SlotIntent:
    language: str
    slot_id: str | None
    confidence: float
    requires_confirmation: bool
    matched_phrase: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "slot_id": self.slot_id,
            "confidence": self.confidence,
            "requires_confirmation": self.requires_confirmation,
            "matched_phrase": self.matched_phrase,
        }


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def normalize_text(text: str) -> str:
    text = text.casefold().strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("–", "-").replace("—", "-")
    return text


def detect_language(text: str) -> str | None:
    """Identify Devanagari or Telugu script, not spoken language."""

    if re.search(r"[\u0c00-\u0c7f]", text):
        return "te"

    if re.search(r"[\u0900-\u097f]", text):
        return "hi"

    return None


def understand_slot_request(
    utterance: str,
    language: str | None = None,
) -> SlotIntent:
    """
    Deterministic phrase matching for a limited demo vocabulary.

    This is NOT a general multilingual NLU model.
    Ambiguous utterances require customer confirmation.
    """

    if not utterance or not utterance.strip():
        raise SlotUnderstandingError("Empty customer utterance")

    detected = detect_language(utterance)

    selected_language = language or detected

    if selected_language not in SUPPORTED_LANGUAGES:
        raise SlotUnderstandingError("Specify Hindi or Telugu for this request")

    normalized = normalize_text(utterance)

    matches: dict[str, str] = {}

    for slot_id, translations in SLOT_ALIASES.items():
        for phrase in translations[selected_language]:
            if normalize_text(phrase) in normalized:
                existing = matches.get(slot_id)

                if existing is None or len(phrase) > len(existing):
                    matches[slot_id] = phrase

    if not matches:
        return SlotIntent(
            language=selected_language,
            slot_id=None,
            confidence=0.0,
            requires_confirmation=True,
            matched_phrase=None,
        )

    # Prefer the longest phrase to reduce accidental
    # matches between overlapping time expressions.
    longest_length = max(len(phrase) for phrase in matches.values())

    strongest = [
        (slot_id, phrase) for slot_id, phrase in matches.items() if len(phrase) == longest_length
    ]

    if len(strongest) != 1:
        return SlotIntent(
            language=selected_language,
            slot_id=None,
            confidence=0.0,
            requires_confirmation=True,
            matched_phrase=None,
        )

    slot_id, phrase = strongest[0]

    return SlotIntent(
        language=selected_language,
        slot_id=slot_id,
        confidence=0.85,
        requires_confirmation=True,
        matched_phrase=phrase,
    )


class DeliverySlotBookingService:
    """SQLite-backed booking workflow with capacity constraints."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB,
        dataset: VizagDatasetService | None = None,
        default_capacity: int = DEFAULT_SLOT_CAPACITY,
    ) -> None:
        if default_capacity < 1:
            raise ValueError("Slot capacity must be positive")

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.dataset = dataset or VizagDatasetService()
        self.default_capacity = default_capacity

        self._initialize_database()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(
            self.db_path,
            timeout=15,
            isolation_level=None,
        )

        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 15000")

        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialize_database(self) -> None:
        with self.transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS delivery_slot_inventory (
                    delivery_date TEXT NOT NULL,
                    slot_id TEXT NOT NULL,
                    merchant_id TEXT NOT NULL,
                    capacity INTEGER NOT NULL,
                    booked_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (
                        delivery_date,
                        slot_id,
                        merchant_id
                    ),
                    CHECK (capacity > 0),
                    CHECK (booked_count >= 0),
                    CHECK (booked_count <= capacity)
                );

                CREATE TABLE IF NOT EXISTS delivery_slot_bookings (
                    booking_id TEXT PRIMARY KEY,
                    shipment_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    merchant_id TEXT NOT NULL,
                    delivery_date TEXT NOT NULL,
                    slot_id TEXT NOT NULL,
                    language TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS
                    ux_active_slot_booking_shipment
                ON delivery_slot_bookings(shipment_id)
                WHERE status = 'confirmed';

                CREATE INDEX IF NOT EXISTS ix_slot_booking_date
                ON delivery_slot_bookings(
                    delivery_date,
                    slot_id,
                    merchant_id
                );

                CREATE TABLE IF NOT EXISTS delivery_slot_events (
                    event_id TEXT PRIMARY KEY,
                    booking_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _event(
        db: sqlite3.Connection,
        booking_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        db.execute(
            """
            INSERT INTO delivery_slot_events (
                event_id, booking_id, event_type,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                new_id("SLOT-EVT"),
                booking_id,
                event_type,
                json.dumps(payload, ensure_ascii=False),
                utc_now(),
            ),
        )

    def _validate_shipment(
        self,
        shipment_id: str,
        customer_id: str,
        merchant_id: str,
    ) -> Any:
        shipment = self.dataset.get_shipment(shipment_id)

        if shipment.customer_id != customer_id:
            raise SlotBookingError("Shipment does not belong to customer")

        if shipment.merchant_id != merchant_id:
            raise SlotBookingError("Shipment does not belong to merchant")

        if shipment.status not in {
            "pending",
            "assigned",
            "out_for_delivery",
        }:
            raise SlotBookingError("Shipment cannot be scheduled in its current status")

        return shipment

    def _ensure_inventory(
        self,
        db: sqlite3.Connection,
        delivery_date: str,
        slot_id: str,
        merchant_id: str,
    ) -> None:
        db.execute(
            """
            INSERT OR IGNORE INTO delivery_slot_inventory (
                delivery_date,
                slot_id,
                merchant_id,
                capacity,
                booked_count
            ) VALUES (?, ?, ?, ?, 0)
            """,
            (
                delivery_date,
                slot_id,
                merchant_id,
                self.default_capacity,
            ),
        )

    def get_availability(
        self,
        delivery_date: str,
        merchant_id: str,
    ) -> list[dict[str, Any]]:
        if not merchant_id.strip():
            raise SlotBookingError("Merchant ID required")

        datetime.strptime(delivery_date, "%Y-%m-%d")

        with self.transaction() as db:
            result = []

            for slot_id, slot in self.dataset.slots.items():
                self._ensure_inventory(
                    db,
                    delivery_date,
                    slot_id,
                    merchant_id,
                )

                inventory = db.execute(
                    """
                    SELECT capacity, booked_count
                    FROM delivery_slot_inventory
                    WHERE delivery_date = ?
                      AND slot_id = ?
                      AND merchant_id = ?
                    """,
                    (
                        delivery_date,
                        slot_id,
                        merchant_id,
                    ),
                ).fetchone()

                available = inventory["capacity"] - inventory["booked_count"]

                result.append(
                    {
                        "slot_id": slot_id,
                        "label": slot["label"],
                        "start_time": slot["start_time"],
                        "end_time": slot["end_time"],
                        "is_overnight": (slot["is_overnight"] == "True"),
                        "capacity": inventory["capacity"],
                        "booked": inventory["booked_count"],
                        "available": available,
                        "is_available": available > 0,
                    }
                )

        return result

    def book_slot(
        self,
        *,
        shipment_id: str,
        customer_id: str,
        merchant_id: str,
        delivery_date: str,
        slot_id: str,
        language: str,
        customer_confirmed: bool,
    ) -> dict[str, Any]:
        if language not in SUPPORTED_LANGUAGES:
            raise SlotBookingError("Unsupported language")

        if not customer_confirmed:
            raise SlotBookingError("Explicit customer confirmation is required")

        shipment = self._validate_shipment(
            shipment_id,
            customer_id,
            merchant_id,
        )

        try:
            delivery_day = datetime.strptime(delivery_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise SlotBookingError("Invalid delivery date") from exc

        if delivery_day.isoformat() != delivery_date:
            raise SlotBookingError("Delivery date must be YYYY-MM-DD")

        if delivery_date != self._get_shipment_delivery_date(shipment_id):
            raise SlotBookingError("Delivery date differs from shipment schedule")

        if slot_id not in self.dataset.slots:
            raise SlotBookingError(f"Unknown delivery slot: {slot_id}")

        booking_id = new_id("BOOKING")
        now = utc_now()

        with self.transaction() as db:
            existing = db.execute(
                """
                SELECT booking_id FROM delivery_slot_bookings
                WHERE shipment_id = ?
                  AND status = 'confirmed'
                """,
                (shipment_id,),
            ).fetchone()

            if existing:
                raise SlotBookingError("Shipment already has a confirmed slot; use reschedule_slot")

            self._ensure_inventory(
                db,
                delivery_date,
                slot_id,
                merchant_id,
            )

            updated = db.execute(
                """
                UPDATE delivery_slot_inventory
                SET booked_count = booked_count + 1
                WHERE delivery_date = ?
                  AND slot_id = ?
                  AND merchant_id = ?
                  AND booked_count < capacity
                """,
                (
                    delivery_date,
                    slot_id,
                    merchant_id,
                ),
            )

            if updated.rowcount != 1:
                raise SlotUnavailableError("Selected slot is fully booked")

            db.execute(
                """
                INSERT INTO delivery_slot_bookings (
                    booking_id, shipment_id, customer_id,
                    merchant_id, delivery_date, slot_id,
                    language, status, confirmed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    booking_id,
                    shipment_id,
                    customer_id,
                    merchant_id,
                    delivery_date,
                    slot_id,
                    language,
                    ACTIVE_BOOKING_STATUS,
                    now,
                    now,
                ),
            )

            self._event(
                db,
                booking_id,
                "slot_booked",
                {
                    "shipment_id": shipment_id,
                    "slot_id": slot_id,
                    "language": language,
                    "customer_confirmed": True,
                },
            )

        return self.get_booking(booking_id)

    def _get_shipment_delivery_date(
        self,
        shipment_id: str,
    ) -> str:
        for row in self.dataset._raw["shipments"]:
            if row["shipment_id"] == shipment_id:
                return row["delivery_date"]

        raise RecordNotFoundError(f"Shipment not found: {shipment_id}")

    def get_booking(
        self,
        booking_id: str,
    ) -> dict[str, Any]:
        with self.transaction() as db:
            row = db.execute(
                """
                SELECT * FROM delivery_slot_bookings
                WHERE booking_id = ?
                """,
                (booking_id,),
            ).fetchone()

            if row is None:
                raise SlotBookingError("Booking not found")

            return dict(row)

    def reschedule_slot(
        self,
        *,
        booking_id: str,
        new_slot_id: str,
        customer_confirmed: bool,
    ) -> dict[str, Any]:
        if not customer_confirmed:
            raise SlotBookingError("Customer confirmation required")

        if new_slot_id not in self.dataset.slots:
            raise SlotBookingError("Unknown delivery slot")

        with self.transaction() as db:
            booking = db.execute(
                """
                SELECT * FROM delivery_slot_bookings
                WHERE booking_id = ?
                """,
                (booking_id,),
            ).fetchone()

            if booking is None:
                raise SlotBookingError("Booking not found")

            if booking["status"] != "confirmed":
                raise SlotBookingError("Only confirmed bookings can be rescheduled")

            old_slot_id = booking["slot_id"]

            if old_slot_id == new_slot_id:
                return dict(booking)

            delivery_date = booking["delivery_date"]
            merchant_id = booking["merchant_id"]

            self._ensure_inventory(
                db,
                delivery_date,
                new_slot_id,
                merchant_id,
            )

            updated = db.execute(
                """
                UPDATE delivery_slot_inventory
                SET booked_count = booked_count + 1
                WHERE delivery_date = ?
                  AND slot_id = ?
                  AND merchant_id = ?
                  AND booked_count < capacity
                """,
                (
                    delivery_date,
                    new_slot_id,
                    merchant_id,
                ),
            )

            if updated.rowcount != 1:
                raise SlotUnavailableError("New slot is fully booked")

            released = db.execute(
                """
                UPDATE delivery_slot_inventory
                SET booked_count = booked_count - 1
                WHERE delivery_date = ?
                  AND slot_id = ?
                  AND merchant_id = ?
                  AND booked_count > 0
                """,
                (
                    delivery_date,
                    old_slot_id,
                    merchant_id,
                ),
            )

            if released.rowcount != 1:
                raise SlotBookingError("Original slot inventory is inconsistent")

            db.execute(
                """
                UPDATE delivery_slot_bookings
                SET slot_id = ?, updated_at = ?
                WHERE booking_id = ?
                """,
                (
                    new_slot_id,
                    utc_now(),
                    booking_id,
                ),
            )

            self._event(
                db,
                booking_id,
                "slot_rescheduled",
                {
                    "old_slot_id": old_slot_id,
                    "new_slot_id": new_slot_id,
                },
            )

        return self.get_booking(booking_id)

    def cancel_booking(
        self,
        booking_id: str,
    ) -> dict[str, Any]:
        with self.transaction() as db:
            booking = db.execute(
                """
                SELECT * FROM delivery_slot_bookings
                WHERE booking_id = ?
                """,
                (booking_id,),
            ).fetchone()

            if booking is None:
                raise SlotBookingError("Booking not found")

            if booking["status"] != "confirmed":
                raise SlotBookingError("Booking is not active")

            updated = db.execute(
                """
                UPDATE delivery_slot_inventory
                SET booked_count = booked_count - 1
                WHERE delivery_date = ?
                  AND slot_id = ?
                  AND merchant_id = ?
                  AND booked_count > 0
                """,
                (
                    booking["delivery_date"],
                    booking["slot_id"],
                    booking["merchant_id"],
                ),
            )

            if updated.rowcount != 1:
                raise SlotBookingError("Slot inventory is inconsistent")

            db.execute(
                """
                UPDATE delivery_slot_bookings
                SET status = 'cancelled',
                    updated_at = ?
                WHERE booking_id = ?
                """,
                (utc_now(), booking_id),
            )

            self._event(
                db,
                booking_id,
                "slot_cancelled",
                {
                    "shipment_id": booking["shipment_id"],
                    "slot_id": booking["slot_id"],
                },
            )

        return self.get_booking(booking_id)

    def get_booking_history(
        self,
        booking_id: str,
    ) -> list[dict[str, Any]]:
        with self.transaction() as db:
            rows = db.execute(
                """
                SELECT * FROM delivery_slot_events
                WHERE booking_id = ?
                ORDER BY created_at, event_id
                """,
                (booking_id,),
            ).fetchall()

        return [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        service = DeliverySlotBookingService(
            db_path=Path(directory) / "slots.sqlite3",
            default_capacity=2,
        )

        hindi = "मुझे दोपहर दो बजे से शाम छह बजे तक डिलीवरी चाहिए।"

        telugu = "నాకు మధ్యాహ్నం రెండు గంటల నుంచి సాయంత్రం ఆరు గంటల వరకు డెలివరీ కావాలి."

        print("HINDI INTENT:")
        print(
            json.dumps(
                understand_slot_request(hindi).to_dict(),
                ensure_ascii=False,
                indent=2,
            )
        )

        print("TELUGU INTENT:")
        print(
            json.dumps(
                understand_slot_request(telugu).to_dict(),
                ensure_ascii=False,
                indent=2,
            )
        )

        booking = service.book_slot(
            shipment_id="SHP-0003",
            customer_id="CUST-0003",
            merchant_id="MERCHANT-DEMO-001",
            delivery_date="2026-11-07",
            slot_id="SLOT-03",
            language="hi",
            customer_confirmed=True,
        )

        print("BOOKED:", booking["booking_id"])
        print("SLOT:", booking["slot_id"])

        booking = service.reschedule_slot(
            booking_id=booking["booking_id"],
            new_slot_id="SLOT-04",
            customer_confirmed=True,
        )

        print("RESCHEDULED:", booking["slot_id"])

        booking = service.cancel_booking(booking["booking_id"])

        print("CANCELLED:", booking["status"])
        print(
            "AUDIT EVENTS:",
            len(service.get_booking_history(booking["booking_id"])),
        )
