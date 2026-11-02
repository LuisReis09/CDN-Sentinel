from __future__ import annotations

import time


def propagation_delay_seconds(distance_km: float, latency_factor: float) -> float:
    """Approximate WAN propagation delay with a controllable multiplier.

    200,000 km/s is a convenient effective speed for a fibre path including
    routing overhead. The minimum keeps localhost requests visibly simulated.
    """
    return min(2.0, max(0.001, (distance_km / 200_000.0) * latency_factor))


def sleep_for_distance(distance_km: float, latency_factor: float) -> float:
    delay = propagation_delay_seconds(distance_km, latency_factor)
    time.sleep(delay)
    return delay

