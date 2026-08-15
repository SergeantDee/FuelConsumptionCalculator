from __future__ import annotations

from dataclasses import dataclass

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES


@dataclass(frozen=True, slots=True)
class BunkerQuantity:
    fuel_type: str
    quantity_mt: float


@dataclass(frozen=True, slots=True)
class PlannedBunker:
    vessel_id: int
    sequence_number: int
    port_snapshot: str
    arrival_snapshot: str | None
    quantities: tuple[BunkerQuantity, ...]

    def quantity_for(self, fuel_type: str) -> float:
        for quantity in self.quantities:
            if quantity.fuel_type == fuel_type:
                return quantity.quantity_mt
        return 0.0


@dataclass(frozen=True, slots=True)
class BunkerCapacity:
    fuel_type: str
    maximum_capacity_mt: float
    target_fill_percent: float

    @property
    def target_rob_mt(self) -> float:
        return self.maximum_capacity_mt * self.target_fill_percent / 100


@dataclass(frozen=True, slots=True)
class BunkerCapacityProfile:
    vessel_id: int
    capacities: tuple[BunkerCapacity, ...]

    def capacity_for(self, fuel_type: str) -> BunkerCapacity:
        for capacity in self.capacities:
            if capacity.fuel_type == fuel_type:
                return capacity
        return BunkerCapacity(fuel_type=fuel_type, maximum_capacity_mt=0.0, target_fill_percent=90.0)


@dataclass(frozen=True, slots=True)
class BunkerPlanStatus:
    plan: PlannedBunker
    status: str


@dataclass(frozen=True, slots=True)
class BunkerLiftLimit:
    fuel_type: str
    capacity_mt: float
    target_fill_percent: float
    target_rob_mt: float
    arrival_rob_mt: float
    max_lift_mt: float


def complete_bunker_plan(
    *,
    vessel_id: int,
    sequence_number: int,
    port_snapshot: str,
    arrival_snapshot: str | None,
    quantities: dict[str, float],
) -> PlannedBunker:
    return PlannedBunker(
        vessel_id=vessel_id,
        sequence_number=sequence_number,
        port_snapshot=port_snapshot,
        arrival_snapshot=arrival_snapshot,
        quantities=tuple(
            BunkerQuantity(fuel_type=fuel_type, quantity_mt=float(quantities.get(fuel_type, 0.0)))
            for fuel_type in FUEL_TYPES
        ),
    )
