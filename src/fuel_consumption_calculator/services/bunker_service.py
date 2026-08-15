from __future__ import annotations

from fuel_consumption_calculator.calculations.bunker_projection_engine import (
    ScheduleBunkerROBProjection,
    project_schedule_rob_with_bunkers,
)
from fuel_consumption_calculator.calculations.consumption_engine import ScheduleFuelConsumption
from fuel_consumption_calculator.domain.bunker import (
    BunkerCapacity,
    BunkerCapacityProfile,
    BunkerLiftLimit,
    BunkerPlanStatus,
    PlannedBunker,
    complete_bunker_plan,
)
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.rob import StartingROB
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.repositories.bunker_repository import BunkerRepository


class BunkerService:
    def __init__(self, repository: BunkerRepository) -> None:
        self._repository = repository

    def build_plan(
        self,
        *,
        vessel_id: int,
        event: ScheduleEvent,
        quantities: dict[str, float],
        lift_limits: dict[str, BunkerLiftLimit] | None = None,
    ) -> PlannedBunker:
        plan = complete_bunker_plan(
            vessel_id=vessel_id,
            sequence_number=event.sequence_number,
            port_snapshot=event.port,
            arrival_snapshot=event.arrival_at.isoformat(timespec="minutes"),
            quantities=quantities,
        )
        self._validate_plan(plan)
        if lift_limits is not None:
            self._validate_lift_limits(plan, lift_limits)
        return plan

    def save_plan(self, plan: PlannedBunker) -> PlannedBunker | None:
        self._validate_plan(plan)
        return self._repository.save_plan(plan, status="DRAFT")

    def confirm_plan(self, plan: PlannedBunker) -> PlannedBunker | None:
        self._validate_plan(plan)
        return self._repository.confirm_plan(plan)

    def load_capacity_profile(self, vessel_id: int) -> BunkerCapacityProfile:
        stored = self._repository.load_capacity_profile(vessel_id)
        stored_capacities = {capacity.fuel_type: capacity for capacity in stored.capacities}
        return BunkerCapacityProfile(
            vessel_id=vessel_id,
            capacities=tuple(
                stored_capacities.get(fuel_type, BunkerCapacity(fuel_type, 0.0, 90.0))
                for fuel_type in FUEL_TYPES
            ),
        )

    def build_capacity_profile(
        self,
        vessel_id: int,
        capacities: dict[str, tuple[float, float]],
    ) -> BunkerCapacityProfile:
        profile = BunkerCapacityProfile(
            vessel_id=vessel_id,
            capacities=tuple(
                BunkerCapacity(
                    fuel_type=fuel_type,
                    maximum_capacity_mt=float(capacities.get(fuel_type, (0.0, 90.0))[0]),
                    target_fill_percent=float(capacities.get(fuel_type, (0.0, 90.0))[1]),
                )
                for fuel_type in FUEL_TYPES
            ),
        )
        self._validate_capacity_profile(profile)
        return profile

    def save_capacity_profile(self, profile: BunkerCapacityProfile) -> BunkerCapacityProfile:
        self._validate_capacity_profile(profile)
        return self.load_capacity_profile(self._repository.save_capacity_profile(profile).vessel_id)

    def calculate_lift_limits(
        self,
        capacity_profile: BunkerCapacityProfile,
        arrival_rob_mt: dict[str, float],
        target_overrides: dict[str, float] | None = None,
    ) -> dict[str, BunkerLiftLimit]:
        limits = {}
        for fuel_type in FUEL_TYPES:
            capacity = capacity_profile.capacity_for(fuel_type)
            target_percent = target_overrides.get(fuel_type, capacity.target_fill_percent) if target_overrides else capacity.target_fill_percent
            if not 0 <= target_percent <= 100:
                raise ValueError("Target fill percentage must be between 0 and 100.")
            target_rob = capacity.maximum_capacity_mt * target_percent / 100
            arrival_rob = arrival_rob_mt.get(fuel_type, 0.0)
            limits[fuel_type] = BunkerLiftLimit(
                fuel_type=fuel_type,
                capacity_mt=capacity.maximum_capacity_mt,
                target_fill_percent=target_percent,
                target_rob_mt=target_rob,
                arrival_rob_mt=arrival_rob,
                max_lift_mt=max(0.0, target_rob - arrival_rob),
            )
        return limits

    def clear_plan(
        self,
        vessel_id: int,
        sequence_number: int,
        port_snapshot: str,
        arrival_snapshot: str | None = None,
    ) -> None:
        self._repository.clear_plan(vessel_id, sequence_number, port_snapshot, arrival_snapshot)

    def list_plan_statuses(self, vessel_id: int, current_events: list[ScheduleEvent]) -> list[BunkerPlanStatus]:
        current_by_sequence = {
            event.sequence_number: event
            for event in current_events
        }
        statuses: list[BunkerPlanStatus] = []
        for plan in self._repository.list_plans(vessel_id):
            current_event = current_by_sequence.get(plan.sequence_number)
            current_arrival_snapshot = current_event.arrival_at.isoformat(timespec="minutes") if current_event else None
            if (
                current_event is not None
                and current_event.port == plan.port_snapshot
                and current_arrival_snapshot == plan.arrival_snapshot
            ):
                status = plan.status
            else:
                status = "STALE"
            statuses.append(BunkerPlanStatus(plan=plan, status=status))
        return statuses

    def active_plans(self, vessel_id: int, current_events: list[ScheduleEvent]) -> list[PlannedBunker]:
        return [
            status.plan
            for status in self.list_plan_statuses(vessel_id, current_events)
            if status.status == "CONFIRMED"
        ]

    def project_schedule_rob_with_bunkers(
        self,
        *,
        starting_rob: StartingROB,
        consumption: ScheduleFuelConsumption,
        active_bunker_plans: list[PlannedBunker],
    ) -> ScheduleBunkerROBProjection:
        return project_schedule_rob_with_bunkers(starting_rob, consumption, active_bunker_plans)

    def _validate_plan(self, plan: PlannedBunker) -> None:
        seen_fuels = set()
        for quantity in plan.quantities:
            if quantity.fuel_type not in FUEL_TYPES:
                raise ValueError(f"Unsupported fuel type: {quantity.fuel_type}.")
            if quantity.fuel_type in seen_fuels:
                raise ValueError(f"Duplicate bunker fuel type: {quantity.fuel_type}.")
            if quantity.quantity_mt < 0:
                raise ValueError("Planned bunker quantities cannot be negative.")
            seen_fuels.add(quantity.fuel_type)
        if seen_fuels != set(FUEL_TYPES):
            raise ValueError("Bunker plan must include ULSFO, VLSFO, and MDO.")
        if plan.status not in {"DRAFT", "CONFIRMED"}:
            raise ValueError("Bunker plan status must be DRAFT or CONFIRMED.")

    def _validate_capacity_profile(self, profile: BunkerCapacityProfile) -> None:
        seen_fuels = set()
        for capacity in profile.capacities:
            if capacity.fuel_type not in FUEL_TYPES:
                raise ValueError(f"Unsupported fuel type: {capacity.fuel_type}.")
            if capacity.fuel_type in seen_fuels:
                raise ValueError(f"Duplicate bunker capacity fuel type: {capacity.fuel_type}.")
            if capacity.maximum_capacity_mt < 0:
                raise ValueError("Bunker capacity cannot be negative.")
            if not 0 <= capacity.target_fill_percent <= 100:
                raise ValueError("Target fill percentage must be between 0 and 100.")
            seen_fuels.add(capacity.fuel_type)
        if seen_fuels != set(FUEL_TYPES):
            raise ValueError("Bunker capacity profile must include ULSFO, VLSFO, and MDO.")

    def _validate_lift_limits(self, plan: PlannedBunker, lift_limits: dict[str, BunkerLiftLimit]) -> None:
        for quantity in plan.quantities:
            limit = lift_limits.get(quantity.fuel_type)
            if limit is not None and quantity.quantity_mt > limit.max_lift_mt:
                raise ValueError(f"Planned {quantity.fuel_type} lift exceeds calculated Max Lift.")
