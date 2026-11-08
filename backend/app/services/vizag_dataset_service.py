"""
DispatchResolve AI — Vizag Dataset and Rescue Matching Service.

Responsibilities
----------------
1. Load and validate synthetic Vizag CSV data.
2. Look up drivers, customers, shipments and planned routes.
3. Identify shipments affected by a driver emergency.
4. Rank replacement drivers using:
   - current availability
   - remaining parcel capacity
   - distance to breakdown location
   - compatibility with the delivery destination
   - approximate route deviation
   - GPS data freshness
5. Produce a deterministic, explainable rescue plan.

Important
---------
This module is a READ-ONLY planning component.

It does not:
- place phone calls
- update shipment assignments
- verify physical parcel handover
- provide actual road navigation
- invoke Gnani AI models

All coordinates and timestamps are synthetic.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DATASET_DIR = Path(__file__).resolve().parents[2] / "data" / "vizag_demo"

EARTH_RADIUS_KM = 6371.0088

ACTIVE_SHIPMENT_STATUSES = frozenset(
    {
        "assigned",
        "out_for_delivery",
    }
)

AVAILABLE_DRIVER_STATUS = "available"

DEFAULT_MAX_PICKUP_DISTANCE_KM = 8.0
DEFAULT_MAX_ROUTE_DEVIATION_KM = 8.0
DEFAULT_MAX_GPS_AGE_MINUTES = 30.0

REQUIRED_FILES = {
    "locations": "locations.csv",
    "drivers": "drivers.csv",
    "customers": "customers.csv",
    "shipments": "shipments.csv",
    "driver_routes": "driver_routes.csv",
    "delivery_slots": "delivery_slots.csv",
    "emergency_scenarios": "emergency_scenarios.csv",
    "voice_scenarios": "voice_scenarios.csv",
}


class DatasetError(RuntimeError):
    """Raised when synthetic dataset contents are invalid."""


class RecordNotFoundError(LookupError):
    """Raised when a requested dataset record does not exist."""


@dataclass(frozen=True, slots=True)
class GeoPoint:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.latitude) and -90 <= self.latitude <= 90):
            raise ValueError("Invalid latitude")

        if not (math.isfinite(self.longitude) and -180 <= self.longitude <= 180):
            raise ValueError("Invalid longitude")


@dataclass(frozen=True, slots=True)
class Driver:
    driver_id: str
    name: str
    phone_alias: str
    preferred_language: str
    position: GeoPoint
    current_location_id: str
    status: str
    available_capacity: int
    gps_last_updated_at: datetime
    merchant_id: str


@dataclass(frozen=True, slots=True)
class Shipment:
    shipment_id: str
    tracking_number: str
    customer_id: str
    assigned_driver_id: str
    merchant_id: str
    delivery_location_id: str
    destination: GeoPoint
    status: str
    preferred_slot_id: str
    slot_confirmation_status: str
    handover_status: str


@dataclass(frozen=True, slots=True)
class RouteStop:
    driver_id: str
    stop_order: int
    location_id: str
    position: GeoPoint
    route_status: str
    merchant_id: str


@dataclass(frozen=True, slots=True)
class RescueCandidate:
    shipment_id: str
    driver_id: str
    driver_name: str
    preferred_language: str
    pickup_distance_km: float
    destination_distance_km: float
    route_deviation_km: float
    available_capacity: int
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "shipment_id": self.shipment_id,
            "driver_id": self.driver_id,
            "driver_name": self.driver_name,
            "preferred_language": self.preferred_language,
            "pickup_distance_km": round(self.pickup_distance_km, 2),
            "destination_distance_km": round(self.destination_distance_km, 2),
            "route_deviation_km": round(self.route_deviation_km, 2),
            "available_capacity": self.available_capacity,
            "score": round(self.score, 3),
        }


@dataclass(frozen=True, slots=True)
class RescueAssignment:
    shipment_id: str
    replacement_driver_id: str
    replacement_driver_name: str
    preferred_language: str
    pickup_distance_km: float
    route_deviation_km: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "shipment_id": self.shipment_id,
            "replacement_driver_id": (self.replacement_driver_id),
            "replacement_driver_name": (self.replacement_driver_name),
            "preferred_language": self.preferred_language,
            "pickup_distance_km": round(self.pickup_distance_km, 2),
            "route_deviation_km": round(self.route_deviation_km, 2),
            "status": "proposed",
        }


def parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DatasetError(f"Invalid datetime: {value!r}") from exc

    if parsed.tzinfo is None:
        raise DatasetError(f"Timezone is required: {value!r}")

    return parsed


def haversine_km(
    point_a: GeoPoint,
    point_b: GeoPoint,
) -> float:
    """Calculate approximate straight-line distance."""

    lat1 = math.radians(point_a.latitude)
    lat2 = math.radians(point_b.latitude)

    delta_lat = lat2 - lat1

    delta_lon = math.radians(point_b.longitude - point_a.longitude)

    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )

    value = min(1.0, max(0.0, value))

    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(value))


def route_length_km(
    points: Iterable[GeoPoint],
) -> float:
    points = list(points)

    return sum(
        haversine_km(start, end)
        for start, end in zip(
            points,
            points[1:],
            strict=False,
        )
    )


def best_route_insertion_km(
    current_position: GeoPoint,
    route: list[GeoPoint],
    pickup: GeoPoint,
    destination: GeoPoint,
) -> float:
    """
    Estimate additional route length when inserting
    pickup before delivery.

    Existing route-stop order is preserved.

    This is a geometric estimate, not road ETA.
    """

    base_route = [
        current_position,
        *route,
    ]

    original_distance = route_length_km(base_route)

    best_extra = math.inf

    # Insert pickup first, then delivery.
    # Existing route stops remain in their original order.
    for pickup_index in range(
        1,
        len(base_route) + 1,
    ):
        with_pickup = base_route.copy()

        with_pickup.insert(
            pickup_index,
            pickup,
        )

        for delivery_index in range(
            pickup_index + 1,
            len(with_pickup) + 1,
        ):
            proposed_route = with_pickup.copy()

            proposed_route.insert(
                delivery_index,
                destination,
            )

            extra_distance = route_length_km(proposed_route) - original_distance

            best_extra = min(
                best_extra,
                extra_distance,
            )

    return max(0.0, best_extra)


class VizagDatasetService:
    """
    Immutable in-memory snapshot of CSV data.

    The dataset is loaded during construction.
    No writes are performed.
    """

    def __init__(
        self,
        dataset_dir: Path | str = DATASET_DIR,
    ) -> None:
        self.dataset_dir = Path(dataset_dir)

        self._raw = {name: self._read_csv(filename) for name, filename in REQUIRED_FILES.items()}

        self.drivers = self._load_drivers()
        self.shipments = self._load_shipments()
        self.routes = self._load_routes()

        self.locations = {row["location_id"]: row for row in self._raw["locations"]}

        self.customers = {row["customer_id"]: row for row in self._raw["customers"]}

        self.slots = {row["slot_id"]: row for row in self._raw["delivery_slots"]}

        self._validate_relationships()

    def _read_csv(
        self,
        filename: str,
    ) -> list[dict[str, str]]:
        path = self.dataset_dir / filename

        if not path.is_file():
            raise DatasetError(f"Required dataset file missing: {path}")

        with path.open(
            "r",
            encoding="utf-8",
            newline="",
        ) as file:
            reader = csv.DictReader(file)

            if not reader.fieldnames:
                raise DatasetError(f"Missing CSV header: {filename}")

            rows = list(reader)

        if not rows:
            raise DatasetError(f"Empty dataset: {filename}")

        return rows

    def _load_drivers(
        self,
    ) -> dict[str, Driver]:
        drivers: dict[str, Driver] = {}

        for row in self._raw["drivers"]:
            driver_id = row["driver_id"]

            if driver_id in drivers:
                raise DatasetError(f"Duplicate driver: {driver_id}")

            capacity = int(row["available_capacity"])

            if capacity < 0:
                raise DatasetError(f"Negative capacity: {driver_id}")

            drivers[driver_id] = Driver(
                driver_id=driver_id,
                name=row["name"],
                phone_alias=row["phone_alias"],
                preferred_language=row["preferred_language"],
                position=GeoPoint(
                    float(row["current_latitude"]),
                    float(row["current_longitude"]),
                ),
                current_location_id=row["current_location_id"],
                status=row["status"],
                available_capacity=capacity,
                gps_last_updated_at=parse_datetime(row["gps_last_updated_at"]),
                merchant_id=row["merchant_id"],
            )

        return drivers

    def _load_shipments(
        self,
    ) -> dict[str, Shipment]:
        shipments: dict[str, Shipment] = {}

        for row in self._raw["shipments"]:
            shipment_id = row["shipment_id"]

            if shipment_id in shipments:
                raise DatasetError(f"Duplicate shipment: {shipment_id}")

            shipments[shipment_id] = Shipment(
                shipment_id=shipment_id,
                tracking_number=row["tracking_number"],
                customer_id=row["customer_id"],
                assigned_driver_id=row["assigned_driver_id"],
                merchant_id=row["merchant_id"],
                delivery_location_id=row["delivery_location_id"],
                destination=GeoPoint(
                    float(row["delivery_latitude"]),
                    float(row["delivery_longitude"]),
                ),
                status=row["status"],
                preferred_slot_id=row["preferred_slot_id"],
                slot_confirmation_status=row["slot_confirmation_status"],
                handover_status=row["handover_status"],
            )

        return shipments

    def _load_routes(
        self,
    ) -> dict[str, list[RouteStop]]:
        routes: dict[str, list[RouteStop]] = {}

        for row in self._raw["driver_routes"]:
            stop = RouteStop(
                driver_id=row["driver_id"],
                stop_order=int(row["stop_order"]),
                location_id=row["location_id"],
                position=GeoPoint(
                    float(row["latitude"]),
                    float(row["longitude"]),
                ),
                route_status=row["route_status"],
                merchant_id=row["merchant_id"],
            )

            routes.setdefault(stop.driver_id, []).append(stop)

        for stops in routes.values():
            stops.sort(key=lambda stop: stop.stop_order)

        return routes

    def _validate_relationships(self) -> None:
        for shipment in self.shipments.values():
            if shipment.assigned_driver_id not in self.drivers:
                raise DatasetError(f"Unknown assigned driver for {shipment.shipment_id}")

            if shipment.customer_id not in self.customers:
                raise DatasetError(f"Unknown customer for {shipment.shipment_id}")

            if shipment.delivery_location_id not in self.locations:
                raise DatasetError(f"Unknown destination for {shipment.shipment_id}")

            if shipment.preferred_slot_id not in self.slots:
                raise DatasetError(f"Unknown delivery slot for {shipment.shipment_id}")

        for driver_id, stops in self.routes.items():
            if driver_id not in self.drivers:
                raise DatasetError(f"Unknown route driver: {driver_id}")

            for stop in stops:
                if stop.location_id not in self.locations:
                    raise DatasetError(f"Unknown route location: {stop.location_id}")

                if stop.merchant_id != self.drivers[driver_id].merchant_id:
                    raise DatasetError(f"Merchant mismatch in route: {driver_id}")

    def get_driver(
        self,
        driver_id: str,
    ) -> Driver:
        try:
            return self.drivers[driver_id]
        except KeyError as exc:
            raise RecordNotFoundError(f"Driver not found: {driver_id}") from exc

    def get_shipment(
        self,
        shipment_id: str,
    ) -> Shipment:
        try:
            return self.shipments[shipment_id]
        except KeyError as exc:
            raise RecordNotFoundError(f"Shipment not found: {shipment_id}") from exc

    def get_driver_shipments(
        self,
        driver_id: str,
        *,
        active_only: bool = True,
    ) -> list[Shipment]:
        self.get_driver(driver_id)

        result = [
            shipment
            for shipment in self.shipments.values()
            if shipment.assigned_driver_id == driver_id
            and (not active_only or shipment.status in ACTIVE_SHIPMENT_STATUSES)
        ]

        return sorted(
            result,
            key=lambda shipment: shipment.shipment_id,
        )

    def get_driver_route(
        self,
        driver_id: str,
    ) -> list[RouteStop]:
        self.get_driver(driver_id)

        return list(self.routes.get(driver_id, []))

    def get_customer_shipments(
        self,
        customer_id: str,
    ) -> list[Shipment]:
        if customer_id not in self.customers:
            raise RecordNotFoundError(f"Customer not found: {customer_id}")

        return sorted(
            [
                shipment
                for shipment in self.shipments.values()
                if shipment.customer_id == customer_id
            ],
            key=lambda shipment: shipment.shipment_id,
        )

    def get_slot(
        self,
        slot_id: str,
    ) -> Mapping[str, str]:
        try:
            return dict(self.slots[slot_id])
        except KeyError as exc:
            raise RecordNotFoundError(f"Slot not found: {slot_id}") from exc

    def rank_rescue_candidates(
        self,
        *,
        failed_driver_id: str,
        shipment_id: str,
        breakdown_location: GeoPoint,
        reference_time: datetime,
        max_pickup_distance_km: float = (DEFAULT_MAX_PICKUP_DISTANCE_KM),
        max_route_deviation_km: float = (DEFAULT_MAX_ROUTE_DEVIATION_KM),
        max_gps_age_minutes: float = (DEFAULT_MAX_GPS_AGE_MINUTES),
    ) -> list[RescueCandidate]:
        """
        Rank drivers for one stranded parcel.

        This is a preliminary matching stage.
        It does not guarantee arrival time or route feasibility.
        """

        if reference_time.tzinfo is None:
            raise ValueError("reference_time must be timezone-aware")

        for value in (
            max_pickup_distance_km,
            max_route_deviation_km,
            max_gps_age_minutes,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Matching thresholds must be positive")

        failed_driver = self.get_driver(failed_driver_id)

        shipment = self.get_shipment(shipment_id)

        if shipment.assigned_driver_id != failed_driver_id:
            raise ValueError("Shipment does not belong to failed driver")

        if shipment.status not in ACTIVE_SHIPMENT_STATUSES:
            raise ValueError("Shipment is not active")

        candidates: list[RescueCandidate] = []

        for driver in self.drivers.values():
            if driver.driver_id == failed_driver_id:
                continue

            if driver.merchant_id != failed_driver.merchant_id:
                continue

            if driver.merchant_id != shipment.merchant_id:
                continue

            if driver.status != AVAILABLE_DRIVER_STATUS:
                continue

            if driver.available_capacity < 1:
                continue

            gps_age_minutes = (
                reference_time.astimezone(UTC) - driver.gps_last_updated_at.astimezone(UTC)
            ).total_seconds() / 60

            if gps_age_minutes < 0 or gps_age_minutes > max_gps_age_minutes:
                continue

            pickup_distance = haversine_km(
                driver.position,
                breakdown_location,
            )

            if pickup_distance > max_pickup_distance_km:
                continue

            route_stops = [
                stop.position
                for stop in self.get_driver_route(driver.driver_id)
                if stop.route_status == "planned"
            ]

            if not route_stops:
                continue

            destination_distance = min(
                haversine_km(
                    stop,
                    shipment.destination,
                )
                for stop in route_stops
            )

            deviation = best_route_insertion_km(
                driver.position,
                route_stops,
                breakdown_location,
                shipment.destination,
            )

            if deviation > max_route_deviation_km:
                continue

            # Lower score = better candidate.
            # Route deviation receives the highest weight.
            score = deviation * 0.60 + pickup_distance * 0.25 + destination_distance * 0.15

            candidates.append(
                RescueCandidate(
                    shipment_id=shipment_id,
                    driver_id=driver.driver_id,
                    driver_name=driver.name,
                    preferred_language=(driver.preferred_language),
                    pickup_distance_km=pickup_distance,
                    destination_distance_km=(destination_distance),
                    route_deviation_km=deviation,
                    available_capacity=(driver.available_capacity),
                    score=score,
                )
            )

        return sorted(
            candidates,
            key=lambda item: (
                item.score,
                item.driver_id,
            ),
        )

    def create_rescue_plan(
        self,
        *,
        failed_driver_id: str,
        breakdown_location: GeoPoint,
        reference_time: datetime,
        max_pickup_distance_km: float = (DEFAULT_MAX_PICKUP_DISTANCE_KM),
        max_route_deviation_km: float = (DEFAULT_MAX_ROUTE_DEVIATION_KM),
        max_gps_age_minutes: float = (DEFAULT_MAX_GPS_AGE_MINUTES),
    ) -> dict[str, Any]:
        """
        Produce a capacity-aware rescue proposal.

        One parcel is allocated to at most one driver.

        The same driver can receive multiple parcels,
        but never more than their available capacity.

        A proposed assignment is NOT a committed assignment.
        """

        failed_driver = self.get_driver(failed_driver_id)

        shipments = self.get_driver_shipments(
            failed_driver_id,
            active_only=True,
        )

        if not shipments:
            return {
                "failed_driver_id": failed_driver_id,
                "status": "no_pending_shipments",
                "assignments": [],
                "unassigned_shipment_ids": [],
            }

        candidate_map: dict[
            str,
            list[RescueCandidate],
        ] = {}

        for shipment in shipments:
            candidate_map[shipment.shipment_id] = self.rank_rescue_candidates(
                failed_driver_id=failed_driver_id,
                shipment_id=shipment.shipment_id,
                breakdown_location=breakdown_location,
                reference_time=reference_time,
                max_pickup_distance_km=(max_pickup_distance_km),
                max_route_deviation_km=(max_route_deviation_km),
                max_gps_age_minutes=(max_gps_age_minutes),
            )

        remaining_capacity = {
            driver.driver_id: driver.available_capacity for driver in self.drivers.values()
        }

        assignments: list[RescueAssignment] = []
        unassigned: list[str] = []

        # Allocate the most constrained parcels first.
        # This avoids assigning an easy parcel before one
        # that has very few eligible drivers.
        ordered_shipments = sorted(
            shipments,
            key=lambda shipment: (
                len(candidate_map[shipment.shipment_id]),
                shipment.shipment_id,
            ),
        )

        for shipment in ordered_shipments:
            candidates = candidate_map[shipment.shipment_id]

            selected = next(
                (
                    candidate
                    for candidate in candidates
                    if remaining_capacity[candidate.driver_id] > 0
                ),
                None,
            )

            if selected is None:
                unassigned.append(shipment.shipment_id)
                continue

            remaining_capacity[selected.driver_id] -= 1

            assignments.append(
                RescueAssignment(
                    shipment_id=shipment.shipment_id,
                    replacement_driver_id=(selected.driver_id),
                    replacement_driver_name=(selected.driver_name),
                    preferred_language=(selected.preferred_language),
                    pickup_distance_km=(selected.pickup_distance_km),
                    route_deviation_km=(selected.route_deviation_km),
                )
            )

        return {
            "failed_driver_id": failed_driver_id,
            "failed_driver_name": failed_driver.name,
            "pending_parcel_count": len(shipments),
            "status": (
                "fully_matched"
                if not unassigned
                else "partially_matched"
                if assignments
                else "no_eligible_drivers"
            ),
            "assignments": [assignment.to_dict() for assignment in assignments],
            "unassigned_shipment_ids": unassigned,
            "requires_driver_acceptance": True,
            "requires_handover_verification": True,
            "requires_dispatcher_approval": True,
            "committed": False,
            "matching_method": ("capacity_aware_greedy_route_insertion"),
            "distance_method": "haversine",
            "location_source": "synthetic",
        }


def get_vizag_dataset_service(
    dataset_dir: Path | str = DATASET_DIR,
) -> VizagDatasetService:
    return VizagDatasetService(dataset_dir)


if __name__ == "__main__":
    import json
    from datetime import timedelta

    service = VizagDatasetService()

    ravi = service.get_driver("DRV-001")

    # Demo dataset GPS timestamps are fixed.
    # Use a matching simulated time, not today's live time.
    simulated_now = ravi.gps_last_updated_at + timedelta(minutes=5)

    plan = service.create_rescue_plan(
        failed_driver_id="DRV-001",
        breakdown_location=ravi.position,
        reference_time=simulated_now,
    )

    print(
        json.dumps(
            plan,
            indent=2,
            ensure_ascii=False,
        )
    )
