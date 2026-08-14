from __future__ import annotations

from dataclasses import dataclass

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES


@dataclass(frozen=True, slots=True)
class ROBQuantity:
    fuel_type: str
    quantity_mt: float


@dataclass(frozen=True, slots=True)
class StartingROB:
    vessel_id: int
    quantities: tuple[ROBQuantity, ...]

    def quantity_for(self, fuel_type: str) -> float:
        for quantity in self.quantities:
            if quantity.fuel_type == fuel_type:
                return quantity.quantity_mt
        return 0.0


def empty_starting_rob(vessel_id: int) -> StartingROB:
    return StartingROB(
        vessel_id=vessel_id,
        quantities=tuple(ROBQuantity(fuel_type, 0.0) for fuel_type in FUEL_TYPES),
    )
