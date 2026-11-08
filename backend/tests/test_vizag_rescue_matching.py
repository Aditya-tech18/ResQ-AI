"""Regression and safety tests for Vizag emergency rescue matching."""

from dataclasses import replace
from datetime import timedelta

import pytest

from app.services.vizag_dataset_service import (
    GeoPoint,
    RecordNotFoundError,
    VizagDatasetService,
    best_route_insertion_km,
    haversine_km,
)


@pytest.fixture
def service():
    return VizagDatasetService()


@pytest.fixture
def demo_time(service):
    return service.get_driver("DRV-001").gps_last_updated_at + timedelta(minutes=5)


@pytest.fixture
def breakdown(service):
    return service.get_driver("DRV-001").position


def plan(service, breakdown, demo_time, **kwargs):
    return service.create_rescue_plan(
        failed_driver_id="DRV-001",
        breakdown_location=breakdown,
        reference_time=demo_time,
        **kwargs,
    )


def test_dataset_has_expected_records(service):
    assert len(service.drivers) == 30
    assert len(service.customers) == 100
    assert len(service.shipments) == 150
    assert len(service.locations) == 12
    assert len(service.slots) == 5


def test_ravi_has_exactly_two_active_shipments(service):
    shipments = service.get_driver_shipments("DRV-001")

    assert {s.shipment_id for s in shipments} == {
        "SHP-0001",
        "SHP-0002",
    }


def test_fixed_demo_fully_matches(service, breakdown, demo_time):
    result = plan(service, breakdown, demo_time)

    assert result["status"] == "fully_matched"
    assert result["pending_parcel_count"] == 2
    assert result["unassigned_shipment_ids"] == []
    assert result["committed"] is False

    assignments = {
        item["shipment_id"]: item["replacement_driver_id"] for item in result["assignments"]
    }

    assert assignments == {
        "SHP-0001": "DRV-002",
        "SHP-0002": "DRV-003",
    }


def test_expected_driver_languages(service, breakdown, demo_time):
    result = plan(service, breakdown, demo_time)

    languages = {
        item["replacement_driver_id"]: item["preferred_language"] for item in result["assignments"]
    }

    assert languages["DRV-002"] == "te"
    assert languages["DRV-003"] == "hi"


def test_failed_driver_never_selected(service, breakdown, demo_time):
    result = plan(service, breakdown, demo_time)

    assert all(item["replacement_driver_id"] != "DRV-001" for item in result["assignments"])


def test_assignments_are_only_proposals(service, breakdown, demo_time):
    result = plan(service, breakdown, demo_time)

    assert result["committed"] is False
    assert result["requires_driver_acceptance"] is True
    assert result["requires_handover_verification"] is True
    assert result["requires_dispatcher_approval"] is True

    assert all(item["status"] == "proposed" for item in result["assignments"])


def test_read_only_planning_does_not_reassign_shipments(service, breakdown, demo_time):
    before = {
        shipment.shipment_id: shipment.assigned_driver_id for shipment in service.shipments.values()
    }

    plan(service, breakdown, demo_time)

    after = {
        shipment.shipment_id: shipment.assigned_driver_id for shipment in service.shipments.values()
    }

    assert before == after


def test_unknown_driver_raises_error(service):
    with pytest.raises(RecordNotFoundError):
        service.get_driver("DRV-DOES-NOT-EXIST")


def test_unknown_shipment_raises_error(service):
    with pytest.raises(RecordNotFoundError):
        service.get_shipment("SHP-DOES-NOT-EXIST")


def test_unknown_slot_raises_error(service):
    with pytest.raises(RecordNotFoundError):
        service.get_slot("SLOT-DOES-NOT-EXIST")


def test_zero_distance():
    location = GeoPoint(17.735, 83.319)
    assert haversine_km(location, location) == pytest.approx(0)


def test_distance_is_symmetric():
    a = GeoPoint(17.735, 83.319)
    b = GeoPoint(17.741, 83.337)

    assert haversine_km(a, b) == pytest.approx(haversine_km(b, a))


@pytest.mark.parametrize(
    "latitude,longitude",
    [
        (91, 80),
        (-91, 80),
        (17, 181),
        (17, -181),
        (float("nan"), 80),
        (17, float("inf")),
    ],
)
def test_invalid_coordinates_rejected(latitude, longitude):
    with pytest.raises(ValueError):
        GeoPoint(latitude, longitude)


def test_route_insertion_preserves_nonnegative_deviation():
    start = GeoPoint(17.735, 83.319)
    route = [
        GeoPoint(17.738, 83.326),
        GeoPoint(17.741, 83.337),
    ]

    deviation = best_route_insertion_km(
        current_position=start,
        route=route,
        pickup=start,
        destination=route[-1],
    )

    assert deviation >= 0
    assert deviation == pytest.approx(0, abs=0.001)


def test_rejects_stale_gps(service, breakdown, demo_time):
    result = plan(
        service,
        breakdown,
        demo_time + timedelta(hours=2),
    )

    assert result["status"] == "no_eligible_drivers"
    assert len(result["assignments"]) == 0


def test_rejects_future_gps(service, breakdown, demo_time):
    result = plan(
        service,
        breakdown,
        demo_time - timedelta(hours=1),
    )

    assert result["status"] == "no_eligible_drivers"


def test_unavailable_drivers_are_not_selected(service, breakdown, demo_time):
    original = service.drivers["DRV-002"]

    service.drivers["DRV-002"] = replace(
        original,
        status="offline",
    )

    candidates = service.rank_rescue_candidates(
        failed_driver_id="DRV-001",
        shipment_id="SHP-0001",
        breakdown_location=breakdown,
        reference_time=demo_time,
    )

    assert "DRV-002" not in {candidate.driver_id for candidate in candidates}


def test_zero_capacity_driver_not_selected(service, breakdown, demo_time):
    original = service.drivers["DRV-003"]

    service.drivers["DRV-003"] = replace(
        original,
        available_capacity=0,
    )

    candidates = service.rank_rescue_candidates(
        failed_driver_id="DRV-001",
        shipment_id="SHP-0002",
        breakdown_location=breakdown,
        reference_time=demo_time,
    )

    assert "DRV-003" not in {candidate.driver_id for candidate in candidates}


def test_wrong_merchant_driver_not_selected(service, breakdown, demo_time):
    original = service.drivers["DRV-002"]

    service.drivers["DRV-002"] = replace(
        original,
        merchant_id="ANOTHER-MERCHANT",
    )

    candidates = service.rank_rescue_candidates(
        failed_driver_id="DRV-001",
        shipment_id="SHP-0001",
        breakdown_location=breakdown,
        reference_time=demo_time,
    )

    assert "DRV-002" not in {candidate.driver_id for candidate in candidates}


def test_capacity_is_not_exceeded(service, breakdown, demo_time):
    result = plan(service, breakdown, demo_time)

    counts = {}

    for assignment in result["assignments"]:
        driver_id = assignment["replacement_driver_id"]
        counts[driver_id] = counts.get(driver_id, 0) + 1

    for driver_id, count in counts.items():
        assert count <= service.drivers[driver_id].available_capacity


def test_duplicate_assignment_never_occurs(service, breakdown, demo_time):
    result = plan(service, breakdown, demo_time)

    shipment_ids = [item["shipment_id"] for item in result["assignments"]]

    assert len(shipment_ids) == len(set(shipment_ids))


def test_strict_distance_threshold_blocks_candidates(service, breakdown, demo_time):
    result = plan(
        service,
        breakdown,
        demo_time,
        max_pickup_distance_km=0.001,
    )

    assert result["status"] == "no_eligible_drivers"


def test_negative_threshold_rejected(service, breakdown, demo_time):
    with pytest.raises(ValueError):
        plan(
            service,
            breakdown,
            demo_time,
            max_pickup_distance_km=-1,
        )


def test_naive_reference_time_rejected(service, breakdown, demo_time):
    with pytest.raises(ValueError):
        plan(
            service,
            breakdown,
            demo_time.replace(tzinfo=None),
        )


def test_no_pending_shipments(service, breakdown, demo_time):
    result = service.create_rescue_plan(
        failed_driver_id="DRV-002",
        breakdown_location=breakdown,
        reference_time=demo_time,
    )

    # DRV-002 may have randomly assigned shipments.
    # Verify internal consistency rather than assume none.
    assert result["pending_parcel_count"] == len(service.get_driver_shipments("DRV-002"))


def test_location_lookup_consistency(service):
    shipment = service.get_shipment("SHP-0001")

    location = service.locations[shipment.delivery_location_id]

    assert location["name"] == "MVP Colony"


def test_slot_data_has_valid_overnight_flag(service):
    overnight = service.get_slot("SLOT-05")

    assert overnight["is_overnight"] == "True"
    assert overnight["start_time"] == "22:00"
    assert overnight["end_time"] == "02:00"
