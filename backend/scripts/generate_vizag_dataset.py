"""
DispatchResolve AI
Synthetic Visakhapatnam Logistics Dataset Generator

Features:
    1. Multilingual delivery slot scheduling
    2. Emergency delivery rescue
    3. Route-aware driver matching
    4. Hindi/Telugu voice-agent demonstrations

Dataset:
    30 drivers
    100 customers
    150 shipments
    12 Vizag delivery zones
    5 delivery slots
    Route plans and stops
    Emergency rescue scenario

Safety:
    All identities and phone numbers are fictional.
    Coordinates are illustrative neighborhood points.
    No real customer or driver information is used.

Usage:
    python scripts/generate_vizag_dataset.py

Requires:
    Python 3.11+
    Standard library only
"""

from __future__ import annotations

import csv
import json
import random
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any


SEED = 20261106
RNG = random.Random(SEED)

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "data" / "vizag_demo"

CITY = "Visakhapatnam"
STATE = "Andhra Pradesh"
COUNTRY = "India"

DEMO_DATE = date(2026, 11, 7)

DRIVER_COUNT = 30
CUSTOMER_COUNT = 100
SHIPMENT_COUNT = 150


@dataclass(frozen=True)
class Location:
    location_id: str
    name: str
    latitude: float
    longitude: float
    city: str = CITY
    state: str = STATE
    country: str = COUNTRY


LOCATIONS = [
    Location("LOC-001", "MVP Colony", 17.7410, 83.3370),
    Location("LOC-002", "Siripuram", 17.7230, 83.3150),
    Location("LOC-003", "Dwaraka Nagar", 17.7290, 83.3000),
    Location("LOC-004", "Maddilapalem", 17.7350, 83.3190),
    Location("LOC-005", "Seethammadhara", 17.7420, 83.3060),
    Location("LOC-006", "Gajuwaka", 17.6850, 83.2100),
    Location("LOC-007", "NAD Junction", 17.7440, 83.2520),
    Location("LOC-008", "Beach Road", 17.7190, 83.3330),
    Location("LOC-009", "Akkayyapalem", 17.7320, 83.2910),
    Location("LOC-010", "PM Palem", 17.7850, 83.3500),
    Location("LOC-011", "Rushikonda", 17.7820, 83.3850),
    Location("LOC-012", "Madhurawada", 17.8010, 83.3550),
]

LOCATION_BY_ID = {
    location.location_id: location
    for location in LOCATIONS
}

LOCATION_BY_NAME = {
    location.name: location
    for location in LOCATIONS
}


DELIVERY_SLOTS = [
    {
        "slot_id": "SLOT-01",
        "start_time": "06:00",
        "end_time": "10:00",
        "label": "6 AM - 10 AM",
        "is_overnight": False,
    },
    {
        "slot_id": "SLOT-02",
        "start_time": "10:00",
        "end_time": "14:00",
        "label": "10 AM - 2 PM",
        "is_overnight": False,
    },
    {
        "slot_id": "SLOT-03",
        "start_time": "14:00",
        "end_time": "18:00",
        "label": "2 PM - 6 PM",
        "is_overnight": False,
    },
    {
        "slot_id": "SLOT-04",
        "start_time": "18:00",
        "end_time": "22:00",
        "label": "6 PM - 10 PM",
        "is_overnight": False,
    },
    {
        "slot_id": "SLOT-05",
        "start_time": "22:00",
        "end_time": "02:00",
        "label": "10 PM - 2 AM",
        "is_overnight": True,
    },
]


FIRST_NAMES = [
    "Ravi",
    "Suresh",
    "Amit",
    "Kiran",
    "Arjun",
    "Vamsi",
    "Rahul",
    "Naveen",
    "Prakash",
    "Ramesh",
    "Sai",
    "Manoj",
    "Vijay",
    "Rohit",
    "Pavan",
    "Deepak",
    "Anil",
    "Mahesh",
    "Varun",
    "Sandeep",
    "Harish",
    "Tarun",
    "Naresh",
    "Nikhil",
    "Rakesh",
    "Ajay",
    "Teja",
    "Vinay",
    "Gopal",
    "Surya",
]

CUSTOMER_FIRST_NAMES = [
    "Rahul",
    "Priya",
    "Anjali",
    "Ramesh",
    "Lakshmi",
    "Kavya",
    "Srinivas",
    "Neha",
    "Arjun",
    "Pooja",
    "Divya",
    "Vijay",
    "Meena",
    "Kiran",
    "Sita",
    "Akhil",
    "Rohit",
    "Swathi",
    "Anusha",
    "Manoj",
]

LAST_NAMES = [
    "Kumar",
    "Reddy",
    "Rao",
    "Sharma",
    "Naidu",
    "Verma",
    "Singh",
    "Patel",
    "Yadav",
    "Prasad",
]


def synthetic_phone_alias(prefix: str, index: int) -> str:
    """
    Return a non-dialable identifier.

    Actual telephony numbers must be stored separately,
    with explicit participant consent.
    """
    return f"DEMO-{prefix}-{index:04d}"


def jitter_coordinate(
    latitude: float,
    longitude: float,
    spread: float = 0.003,
) -> tuple[float, float]:
    return (
        round(latitude + RNG.uniform(-spread, spread), 6),
        round(longitude + RNG.uniform(-spread, spread), 6),
    )


def write_csv(
    filename: str,
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        raise ValueError(f"Cannot write empty dataset: {filename}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    destination = OUTPUT_DIR / filename

    fieldnames = list(rows[0].keys())

    with destination.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"[CREATED] {filename}: {len(rows)} records")


def generate_locations() -> list[dict[str, Any]]:
    return [
        asdict(location)
        for location in LOCATIONS
    ]


def generate_drivers() -> list[dict[str, Any]]:
    drivers = []

    for index in range(1, DRIVER_COUNT + 1):
        location = LOCATIONS[(index - 1) % len(LOCATIONS)]

        latitude, longitude = jitter_coordinate(
            location.latitude,
            location.longitude,
        )

        if index == 1:
            name = "Ravi Kumar"
            language = "hi"
            status = "emergency"
            capacity = 0
            location = LOCATION_BY_NAME["Maddilapalem"]
            latitude = 17.7350
            longitude = 83.3190

        elif index == 2:
            name = "Suresh Reddy"
            language = "te"
            status = "available"
            capacity = 2
            location = LOCATION_BY_NAME["MVP Colony"]
            latitude = 17.7380
            longitude = 83.3260

        elif index == 3:
            name = "Amit Sharma"
            language = "hi"
            status = "available"
            capacity = 2
            location = LOCATION_BY_NAME["Siripuram"]
            latitude = 17.7280
            longitude = 83.3170

        else:
            name = (
                f"{FIRST_NAMES[index - 1]} "
                f"{LAST_NAMES[(index - 1) % len(LAST_NAMES)]}"
            )

            language = RNG.choice(["hi", "te"])

            status = RNG.choices(
                ["available", "busy", "offline"],
                weights=[65, 25, 10],
                k=1,
            )[0]

            capacity = (
                RNG.randint(1, 6)
                if status == "available"
                else 0
            )

        drivers.append(
            {
                "driver_id": f"DRV-{index:03d}",
                "name": name,
                "phone_alias": synthetic_phone_alias(
                    "DRIVER", index
                ),
                "preferred_language": language,
                "current_latitude": latitude,
                "current_longitude": longitude,
                "current_location_id": location.location_id,
                "status": status,
                "available_capacity": capacity,
                "vehicle_type": "two_wheeler",
                "shift_start": "08:00",
                "shift_end": "22:00",
                "location_source": "synthetic",
                "gps_last_updated_at": (
                    "2026-11-07T10:00:00+05:30"
                ),
                "merchant_id": "MERCHANT-DEMO-001",
            }
        )

    return drivers


def generate_customers() -> list[dict[str, Any]]:
    customers = []

    for index in range(1, CUSTOMER_COUNT + 1):
        location = RNG.choice(LOCATIONS)

        latitude, longitude = jitter_coordinate(
            location.latitude,
            location.longitude,
            spread=0.0015,
        )

        first_name = RNG.choice(CUSTOMER_FIRST_NAMES)
        last_name = RNG.choice(LAST_NAMES)

        customers.append(
            {
                "customer_id": f"CUST-{index:04d}",
                "name": f"{first_name} {last_name}",
                "phone_alias": synthetic_phone_alias(
                    "CUSTOMER", index
                ),
                "preferred_language": RNG.choice(["hi", "te"]),
                "location_id": location.location_id,
                "address_line": (
                    f"Demo Address {index}, {location.name}"
                ),
                "latitude": latitude,
                "longitude": longitude,
                "city": CITY,
                "state": STATE,
                "country": COUNTRY,
                "merchant_id": "MERCHANT-DEMO-001",
            }
        )

    return customers


def generate_shipments(
    customers: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    shipments = []

    driver_ids = [
        driver["driver_id"]
        for driver in drivers
        if driver["driver_id"] != "DRV-001"
    ]

    for index in range(1, SHIPMENT_COUNT + 1):
        customer = customers[(index - 1) % len(customers)]

        shipment_id = f"SHP-{index:04d}"

        assigned_driver = RNG.choice(driver_ids)
        status = RNG.choice(
            ["pending", "assigned", "out_for_delivery"]
        )

        if index == 1:
            assigned_driver = "DRV-001"
            status = "out_for_delivery"

            location = LOCATION_BY_NAME["MVP Colony"]
            latitude = location.latitude
            longitude = location.longitude

        elif index == 2:
            assigned_driver = "DRV-001"
            status = "out_for_delivery"

            location = LOCATION_BY_NAME["Siripuram"]
            latitude = location.latitude
            longitude = location.longitude

        else:
            location = LOCATION_BY_ID[
                customer["location_id"]
            ]
            latitude = customer["latitude"]
            longitude = customer["longitude"]

        slot = RNG.choice(DELIVERY_SLOTS[:4])

        shipments.append(
            {
                "shipment_id": shipment_id,
                "tracking_number": f"DRAI-VZG-{index:06d}",
                "customer_id": customer["customer_id"],
                "assigned_driver_id": assigned_driver,
                "merchant_id": "MERCHANT-DEMO-001",
                "pickup_location_id": "LOC-003",
                "delivery_location_id": location.location_id,
                "delivery_latitude": latitude,
                "delivery_longitude": longitude,
                "status": status,
                "delivery_date": DEMO_DATE.isoformat(),
                "preferred_slot_id": slot["slot_id"],
                "slot_confirmation_status": "pending",
                "parcel_weight_kg": round(
                    RNG.uniform(0.2, 4.0), 2
                ),
                "parcel_size": RNG.choice(
                    ["small", "medium", "large"]
                ),
                "requires_otp": True,
                "handover_status": "not_started",
                "rescue_case_id": "",
                "created_at": (
                    "2026-11-07T08:00:00+05:30"
                ),
            }
        )

    return shipments


def generate_driver_routes(
    drivers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    routes = []

    for driver in drivers:
        driver_id = driver["driver_id"]

        if driver_id == "DRV-001":
            destinations = [
                "MVP Colony",
                "Siripuram",
            ]

        elif driver_id == "DRV-002":
            destinations = [
                "Maddilapalem",
                "MVP Colony",
            ]

        elif driver_id == "DRV-003":
            destinations = [
                "Maddilapalem",
                "Siripuram",
            ]

        else:
            start_index = RNG.randrange(len(LOCATIONS))
            destinations = [
                LOCATIONS[start_index].name,
                LOCATIONS[
                    (start_index + 1) % len(LOCATIONS)
                ].name,
            ]

        for stop_order, destination in enumerate(
            destinations,
            start=1,
        ):
            location = LOCATION_BY_NAME[destination]

            routes.append(
                {
                    "route_id": (
                        f"ROUTE-{driver_id}-{stop_order:02d}"
                    ),
                    "driver_id": driver_id,
                    "stop_order": stop_order,
                    "location_id": location.location_id,
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                    "stop_type": "delivery_zone",
                    "planned_arrival": (
                        "2026-11-07T12:00:00+05:30"
                        if stop_order == 1
                        else "2026-11-07T14:00:00+05:30"
                    ),
                    "route_status": "planned",
                    "merchant_id": "MERCHANT-DEMO-001",
                }
            )

    return routes


def generate_emergency_scenarios() -> list[dict[str, Any]]:
    return [
        {
            "scenario_id": "EMG-VZG-001",
            "failed_driver_id": "DRV-001",
            "emergency_type": "vehicle_breakdown",
            "emergency_status": "reported",
            "breakdown_latitude": 17.7350,
            "breakdown_longitude": 83.3190,
            "pending_shipment_ids": (
                "SHP-0001|SHP-0002"
            ),
            "pending_parcel_count": 2,
            "suggested_driver_1": "DRV-002",
            "suggested_driver_2": "DRV-003",
            "driver_1_target_shipment": "SHP-0001",
            "driver_2_target_shipment": "SHP-0002",
            "initial_language": "hi",
            "driver_1_switch_language": "te",
            "driver_2_language": "hi",
            "requires_driver_acceptance": True,
            "requires_handover_verification": True,
            "requires_dispatcher_approval": True,
            "merchant_id": "MERCHANT-DEMO-001",
        }
    ]


def generate_voice_scenarios() -> list[dict[str, Any]]:
    return [
        {
            "scenario_id": "VOICE-001",
            "participant": "Ravi",
            "participant_id": "DRV-001",
            "language": "hi",
            "intent": "report_vehicle_breakdown",
            "utterance": (
                "मेरी बाइक खराब हो गई है। "
                "मेरे दो पार्सल डिलीवर होने बाकी हैं।"
            ),
            "expected_action": "create_rescue_case",
        },
        {
            "scenario_id": "VOICE-002",
            "participant": "Suresh",
            "participant_id": "DRV-002",
            "language": "te",
            "intent": "request_language_switch",
            "utterance": (
                "నాకు హిందీ అర్థం కావడం లేదు. "
                "దయచేసి తెలుగులో మాట్లాడండి."
            ),
            "expected_action": "switch_to_telugu",
        },
        {
            "scenario_id": "VOICE-003",
            "participant": "Suresh",
            "participant_id": "DRV-002",
            "language": "te",
            "intent": "accept_rescue",
            "utterance": (
                "సరే, నేను రవి దగ్గరకు వెళ్లి "
                "పార్సెల్ తీసుకుంటాను."
            ),
            "expected_action": "record_driver_acceptance",
        },
        {
            "scenario_id": "VOICE-004",
            "participant": "Amit",
            "participant_id": "DRV-003",
            "language": "hi",
            "intent": "accept_rescue",
            "utterance": (
                "हाँ, मैं रवि की लोकेशन पर आकर "
                "पार्सल ले सकता हूँ।"
            ),
            "expected_action": "record_driver_acceptance",
        },
        {
            "scenario_id": "VOICE-005",
            "participant": "Customer",
            "participant_id": "CUST-0001",
            "language": "hi",
            "intent": "select_delivery_slot",
            "utterance": (
                "मुझे दोपहर दो बजे से "
                "शाम छह बजे तक डिलीवरी चाहिए।"
            ),
            "expected_action": "request_slot_03",
        },
        {
            "scenario_id": "VOICE-006",
            "participant": "Customer",
            "participant_id": "CUST-0002",
            "language": "te",
            "intent": "select_delivery_slot",
            "utterance": (
                "నాకు మధ్యాహ్నం రెండు గంటల నుంచి "
                "సాయంత్రం ఆరు గంటల వరకు డెలివరీ కావాలి."
            ),
            "expected_action": "request_slot_03",
        },
    ]


def validate_dataset(
    drivers: list[dict[str, Any]],
    customers: list[dict[str, Any]],
    shipments: list[dict[str, Any]],
    routes: list[dict[str, Any]],
) -> None:
    assert len(drivers) == DRIVER_COUNT
    assert len(customers) == CUSTOMER_COUNT
    assert len(shipments) == SHIPMENT_COUNT
    assert len(routes) == DRIVER_COUNT * 2

    driver_ids = {
        driver["driver_id"]
        for driver in drivers
    }

    customer_ids = {
        customer["customer_id"]
        for customer in customers
    }

    shipment_ids = {
        shipment["shipment_id"]
        for shipment in shipments
    }

    assert len(driver_ids) == len(drivers)
    assert len(customer_ids) == len(customers)
    assert len(shipment_ids) == len(shipments)

    for shipment in shipments:
        assert shipment["assigned_driver_id"] in driver_ids
        assert shipment["customer_id"] in customer_ids
        assert (
            shipment["delivery_location_id"]
            in LOCATION_BY_ID
        )

    for route in routes:
        assert route["driver_id"] in driver_ids
        assert route["location_id"] in LOCATION_BY_ID

    assert (
        shipments[0]["assigned_driver_id"] == "DRV-001"
    )
    assert (
        shipments[1]["assigned_driver_id"] == "DRV-001"
    )

    assert (
        shipments[0]["delivery_location_id"]
        == "LOC-001"
    )
    assert (
        shipments[1]["delivery_location_id"]
        == "LOC-002"
    )

    print("[VALIDATED] Dataset relationships are consistent")


def write_manifest(
    drivers: list[dict[str, Any]],
    customers: list[dict[str, Any]],
    shipments: list[dict[str, Any]],
) -> None:
    manifest = {
        "project": "DispatchResolve AI",
        "dataset_name": "Vizag Synthetic Logistics Demo",
        "dataset_version": "1.0.0",
        "synthetic": True,
        "city": CITY,
        "state": STATE,
        "country": COUNTRY,
        "random_seed": SEED,
        "demo_date": DEMO_DATE.isoformat(),
        "driver_count": len(drivers),
        "customer_count": len(customers),
        "shipment_count": len(shipments),
        "supported_languages": ["hi", "te"],
        "features": [
            "delivery_slot_booking",
            "emergency_delivery_rescue",
        ],
        "limitations": [
            "Coordinates are illustrative.",
            "Phone aliases are not dialable.",
            "Route times are simulated.",
            "No live GPS is included.",
            "No real customer data is included.",
        ],
        "driver_status_counts": dict(
            Counter(
                driver["status"]
                for driver in drivers
            )
        ),
        "shipment_status_counts": dict(
            Counter(
                shipment["status"]
                for shipment in shipments
            )
        ),
    }

    path = OUTPUT_DIR / "manifest.json"

    path.write_text(
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("[CREATED] manifest.json")


def main() -> None:
    print("=" * 60)
    print("DISPATCHRESOLVE AI — VIZAG DATASET GENERATOR")
    print("=" * 60)

    drivers = generate_drivers()
    customers = generate_customers()

    shipments = generate_shipments(
        customers,
        drivers,
    )

    routes = generate_driver_routes(drivers)

    validate_dataset(
        drivers,
        customers,
        shipments,
        routes,
    )

    datasets = {
        "locations.csv": generate_locations(),
        "drivers.csv": drivers,
        "customers.csv": customers,
        "shipments.csv": shipments,
        "driver_routes.csv": routes,
        "delivery_slots.csv": DELIVERY_SLOTS,
        "emergency_scenarios.csv": (
            generate_emergency_scenarios()
        ),
        "voice_scenarios.csv": generate_voice_scenarios(),
    }

    for filename, rows in datasets.items():
        write_csv(filename, rows)

    write_manifest(
        drivers,
        customers,
        shipments,
    )

    print()
    print("=" * 60)
    print("DATASET GENERATION COMPLETE")
    print("=" * 60)

    print(f"Output: {OUTPUT_DIR}")
    print(f"Drivers: {len(drivers)}")
    print(f"Customers: {len(customers)}")
    print(f"Shipments: {len(shipments)}")
    print(f"Route stops: {len(routes)}")

    print()
    print("Fixed emergency demo:")
    print("  Ravi   -> DRV-001")
    print("  Suresh -> DRV-002")
    print("  Amit   -> DRV-003")
    print("  Parcel 1 -> MVP Colony")
    print("  Parcel 2 -> Siripuram")

    print()
    print("All records are synthetic.")
    print("No real calls have been initiated.")


if __name__ == "__main__":
    main()
