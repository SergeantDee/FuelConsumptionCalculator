from __future__ import annotations

from fuel_consumption_calculator.calculations.consumption_engine import ScheduleFuelConsumption
from fuel_consumption_calculator.calculations.rob_projection_engine import ScheduleROBProjection, project_schedule_rob
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.rob import ROBQuantity, StartingROB
from fuel_consumption_calculator.repositories.rob_repository import ROBRepository


class ROBService:
    def __init__(self, repository: ROBRepository) -> None:
        self._repository = repository

    def load_starting_rob(self, vessel_id: int) -> StartingROB:
        stored = self._repository.load_starting_rob(vessel_id)
        stored_quantities = {
            quantity.fuel_type: quantity.quantity_mt
            for quantity in stored.quantities
        }
        return StartingROB(
            vessel_id=vessel_id,
            quantities=tuple(
                ROBQuantity(fuel_type=fuel_type, quantity_mt=stored_quantities.get(fuel_type, 0.0))
                for fuel_type in FUEL_TYPES
            ),
        )

    def build_starting_rob(self, vessel_id: int, quantities: dict[str, float]) -> StartingROB:
        starting_rob = StartingROB(
            vessel_id=vessel_id,
            quantities=tuple(
                ROBQuantity(fuel_type=fuel_type, quantity_mt=float(quantities.get(fuel_type, 0.0)))
                for fuel_type in FUEL_TYPES
            ),
        )
        self._validate_starting_rob(starting_rob)
        return starting_rob

    def save_starting_rob(self, starting_rob: StartingROB) -> StartingROB:
        self._validate_starting_rob(starting_rob)
        return self.load_starting_rob(self._repository.save_starting_rob(starting_rob).vessel_id)

    def project_schedule_rob(
        self,
        vessel_id: int,
        consumption: ScheduleFuelConsumption,
    ) -> ScheduleROBProjection:
        return project_schedule_rob(self.load_starting_rob(vessel_id), consumption)

    def _validate_starting_rob(self, starting_rob: StartingROB) -> None:
        expected_fuels = set(FUEL_TYPES)
        seen_fuels = set()
        for quantity in starting_rob.quantities:
            if quantity.fuel_type not in expected_fuels:
                raise ValueError(f"Unsupported fuel type: {quantity.fuel_type}.")
            if quantity.fuel_type in seen_fuels:
                raise ValueError(f"Duplicate starting ROB fuel type: {quantity.fuel_type}.")
            if quantity.quantity_mt < 0:
                raise ValueError("Starting ROB quantities cannot be negative.")
            seen_fuels.add(quantity.fuel_type)
        if seen_fuels != expected_fuels:
            raise ValueError("Starting ROB must include ULSFO, VLSFO, and MDO.")
