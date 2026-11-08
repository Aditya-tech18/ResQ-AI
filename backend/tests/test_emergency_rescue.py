import pytest

from app.services.emergency_rescue import (
    RescueDriver,
    recommend_rescue_drivers,
)


def test_rescue_splits_eight_parcels():
    drivers = [
        RescueDriver("suresh", "hyd", 5, True),
        RescueDriver("amit", "hyd", 3, True),
        RescueDriver("kiran", "delhi", 6, True),
    ]

    result = recommend_rescue_drivers(
        region_id="hyd",
        failed_driver_id="ravi",
        pending_parcels=8,
        drivers=drivers,
    )

    assert [(r.driver_id, r.parcels_to_assign) for r in result] == [
        ("suresh", 5),
        ("amit", 3),
    ]


def test_failed_driver_is_excluded():
    drivers = [
        RescueDriver("ravi", "hyd", 10, True),
        RescueDriver("suresh", "hyd", 2, True),
    ]

    result = recommend_rescue_drivers(
        region_id="hyd",
        failed_driver_id="ravi",
        pending_parcels=2,
        drivers=drivers,
    )

    assert [r.driver_id for r in result] == ["suresh"]


def test_unavailable_driver_is_excluded():
    drivers = [
        RescueDriver("suresh", "hyd", 5, False),
    ]

    result = recommend_rescue_drivers(
        region_id="hyd",
        failed_driver_id="ravi",
        pending_parcels=3,
        drivers=drivers,
    )

    assert result == []


def test_emergency_driver_is_excluded():
    drivers = [
        RescueDriver("suresh", "hyd", 5, True, True),
    ]

    result = recommend_rescue_drivers(
        region_id="hyd",
        failed_driver_id="ravi",
        pending_parcels=3,
        drivers=drivers,
    )

    assert result == []


def test_insufficient_capacity_never_overassigns():
    drivers = [
        RescueDriver("suresh", "hyd", 2, True),
    ]

    result = recommend_rescue_drivers(
        region_id="hyd",
        failed_driver_id="ravi",
        pending_parcels=8,
        drivers=drivers,
    )

    assert sum(r.parcels_to_assign for r in result) == 2


def test_invalid_pending_parcels():
    with pytest.raises(ValueError):
        recommend_rescue_drivers(
            region_id="hyd",
            failed_driver_id="ravi",
            pending_parcels=0,
            drivers=[],
        )
