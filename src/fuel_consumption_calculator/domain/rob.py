from __future__ import annotations

from dataclasses import dataclass

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES


@dataclass(frozen=True, slots=True)
class ROBQuantity:
    fuel_type: str
    quantity_mt: float | None


@dataclass(frozen=True, slots=True)
class StartingROB:
    vessel_id: int
    quantities: tuple[ROBQuantity, ...]

    def quantity_for(self, fuel_type: str) -> float | None:
        for quantity in self.quantities:
            if quantity.fuel_type == fuel_type:
                return quantity.quantity_mt
        return None


def empty_starting_rob(vessel_id: int) -> StartingROB:
    return StartingROB(
        vessel_id=vessel_id,
        quantities=tuple(ROBQuantity(fuel_type, None) for fuel_type in FUEL_TYPES),
    )
