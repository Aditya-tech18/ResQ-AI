from dataclasses import dataclass


@dataclass(frozen=True)
class RescueDriver:
    driver_id: str
    region_id: str
    available_capacity: int
    is_available: bool
    active_emergency: bool = False


@dataclass(frozen=True)
class RescueRecommendation:
    driver_id: str
    parcels_to_assign: int


def recommend_rescue_drivers(
    *,
    region_id: str,
    failed_driver_id: str,
    pending_parcels: int,
    drivers: list[RescueDriver],
) -> list[RescueRecommendation]:
    """Recommend capacity-based rescue assignments.

    Does not modify shipment assignments or contact drivers.
    """
    if pending_parcels <= 0:
        raise ValueError("pending_parcels must be positive")

    eligible = [
        driver
        for driver in drivers
        if driver.driver_id != failed_driver_id
        and driver.region_id == region_id
        and driver.is_available
        and not driver.active_emergency
        and driver.available_capacity > 0
    ]

    eligible.sort(
        key=lambda driver: (
            -driver.available_capacity,
            driver.driver_id,
        )
    )

    remaining = pending_parcels
    recommendations = []

    for driver in eligible:
        if remaining == 0:
            break

        assigned = min(driver.available_capacity, remaining)

        recommendations.append(
            RescueRecommendation(
                driver_id=driver.driver_id,
                parcels_to_assign=assigned,
            )
        )

        remaining -= assigned

    return recommendations
