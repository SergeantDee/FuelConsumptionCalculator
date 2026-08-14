from __future__ import annotations

from dataclasses import dataclass


OPERATING_MODES = ("SEA", "PORT")
FUEL_TYPES = ("ULSFO", "VLSFO", "MDO")


@dataclass(frozen=True, slots=True)
class ConsumptionRate:
    operating_mode: str
    fuel_type: str
    rate_mt_per_day: float


@dataclass(frozen=True, slots=True)
class ConsumptionProfile:
    vessel_id: int
    rates: tuple[ConsumptionRate, ...]

    def rate_for(self, operating_mode: str, fuel_type: str) -> float:
        for rate in self.rates:
            if rate.operating_mode == operating_mode and rate.fuel_type == fuel_type:
                return rate.rate_mt_per_day
        return 0.0
