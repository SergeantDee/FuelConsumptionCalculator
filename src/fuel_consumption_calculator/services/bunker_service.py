from __future__ import annotations

from datetime import datetime, timezone

from fuel_consumption_calculator.calculations.bunker_projection_engine import (
    ScheduleBunkerROBProjection,
    project_schedule_rob_with_bunkers,
)
from fuel_consumption_calculator.calculations.consumption_engine import ScheduleFuelConsumption
from fuel_consumption_calculator.calculations.tank_max_lift import SelectedReceivingTank, TankMaxLiftResult, calculate_tank_max_lift
from fuel_consumption_calculator.domain.bunker import (
    BunkerCapacity,
    BunkerCapacityProfile,
    BunkerLiftLimit,
    BunkerPlanStatus,
    BunkerIncomingFuelSnapshot,
    BunkerReceivingTankPlan,
    ReceivingTankArrivalProjection,
    PlannedBunker,
    complete_bunker_plan,
)
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.rob import StartingROB
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.repositories.bunker_repository import BunkerRepository
from fuel_consumption_calculator.services.tank_forecast_service import TankForecastService


class BunkerService:
    def __init__(self, repository: BunkerRepository, tank_forecast_service: TankForecastService | None = None) -> None:
        self._repository = repository
        self._tank_forecast_service = tank_forecast_service

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
            arrival_snapshot=event.effective_arrival_at.isoformat(timespec="minutes"),
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
        arrival_rob_mt: dict[str, float | None],
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
            max_lift = None if arrival_rob is None else max(0.0, target_rob - arrival_rob)
            limits[fuel_type] = BunkerLiftLimit(
                fuel_type=fuel_type,
                capacity_mt=capacity.maximum_capacity_mt,
                target_fill_percent=target_percent,
                target_rob_mt=target_rob,
                arrival_rob_mt=arrival_rob,
                max_lift_mt=max_lift,
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

    def list_eligible_receiving_tanks(self, vessel_id: int):
        return self._repository.list_eligible_receiving_tanks(vessel_id)

    def list_fuel_batches(self, vessel_id: int):
        return self._repository.list_fuel_batches(vessel_id)

    def save_receiving_tank_plan(self, plan: PlannedBunker, rows: list[BunkerReceivingTankPlan], incoming_batch_id: int | None, manual_vcf: float | None) -> None:
        batches = {batch.id: batch for batch in self.list_fuel_batches(plan.vessel_id)}
        if incoming_batch_id is not None and incoming_batch_id not in batches:
            raise ValueError("Incoming fuel batch must belong to the bunker-plan vessel.")
        tank_ids = [row.tank_id for row in rows]
        if len(tank_ids) != len(set(tank_ids)):
            raise ValueError("A receiving tank can only be selected once per bunker plan.")
        eligible = {tank.id: tank for tank, _latest in self.list_eligible_receiving_tanks(plan.vessel_id)}
        for row in rows:
            if row.tank_id not in eligible:
                raise ValueError("Selected receiving tanks must be active eligible bunker tanks.")
            if row.projected_arrival_volume_m3 is not None and row.projected_arrival_volume_m3 < 0:
                raise ValueError("Projected arrival volume must be at least 0.")
            if not 0 < row.target_fill_percent <= 100:
                raise ValueError("Target fill percent must be greater than 0 and at most 100.")
        if manual_vcf is not None and manual_vcf <= 0:
            raise ValueError("Incoming Manual VCF must be greater than 0.")
        density = batches[incoming_batch_id].density_15_kg_m3 if incoming_batch_id is not None else None
        self._repository.save_receiving_tank_plan(plan, rows, BunkerIncomingFuelSnapshot(incoming_batch_id, density, manual_vcf))

    def list_receiving_tank_plan(self, plan: PlannedBunker) -> list[BunkerReceivingTankPlan]:
        return self._repository.list_receiving_tank_plan(plan)

    def load_incoming_fuel_snapshot(self, plan: PlannedBunker) -> BunkerIncomingFuelSnapshot:
        return self._repository.load_incoming_fuel_snapshot(plan)

    def clear_receiving_tank_plan(self, plan: PlannedBunker) -> None:
        self._repository.save_receiving_tank_plan(plan, [], BunkerIncomingFuelSnapshot(None, None, None))

    def tank_based_max_lift(self, plan: PlannedBunker) -> TankMaxLiftResult | None:
        rows = self._repository.list_receiving_tank_plan(plan)
        if not rows:
            return None
        tanks = {tank.id: tank for tank, _latest in self._repository.list_eligible_receiving_tanks(plan.vessel_id)}
        projections = self.resolve_receiving_tank_arrivals(plan, rows)
        if any(row.tank_id not in tanks or projections[row.tank_id].projected_arrival_volume_m3 is None for row in rows):
            return None
        incoming = self._repository.load_incoming_fuel_snapshot(plan)
        return calculate_tank_max_lift([SelectedReceivingTank(row.tank_id, tanks[row.tank_id].capacity_m3, projections[row.tank_id].projected_arrival_volume_m3, row.target_fill_percent) for row in rows], incoming_density_15_kg_m3=incoming.density_15_kg_m3, incoming_manual_vcf=incoming.manual_vcf)

    def resolve_receiving_tank_arrivals(
        self, plan: PlannedBunker, rows: list[BunkerReceivingTankPlan] | None = None,
    ) -> dict[int, ReceivingTankArrivalProjection]:
        """Resolve manual overrides before advisory forecasts at bunker arrival UTC."""
        rows = rows if rows is not None else self.list_receiving_tank_plan(plan)
        result: dict[int, ReceivingTankArrivalProjection] = {}
        automatic = []
        for row in rows:
            if row.projected_arrival_volume_m3 is not None:
                result[row.tank_id] = ReceivingTankArrivalProjection(row.tank_id, row.projected_arrival_volume_m3, "MANUAL")
            else:
                automatic.append(row)
        if not automatic:
            return result
        if self._tank_forecast_service is None:
            return {**result, **{row.tank_id: ReceivingTankArrivalProjection(row.tank_id, None, "UNAVAILABLE", "Tank forecast service is unavailable.") for row in automatic}}
        target_utc = _arrival_utc(plan.arrival_snapshot)
        if target_utc is None:
            return {**result, **{row.tank_id: ReceivingTankArrivalProjection(row.tank_id, None, "UNAVAILABLE", "Bunker arrival time is unavailable.") for row in automatic}}
        forecasts = {forecast.tank_id: forecast for forecast in self._tank_forecast_service.predict_tank_rob_at(plan.vessel_id, target_utc)}
        for row in automatic:
            forecast = forecasts.get(row.tank_id)
            if forecast is None or forecast.predicted_mass_mt is None:
                result[row.tank_id] = ReceivingTankArrivalProjection(row.tank_id, None, "UNAVAILABLE", forecast.issue if forecast else "Tank forecast could not be established.")
                continue
            anchor = self._tank_forecast_service.anchor_sounding_at(row.tank_id, target_utc)
            if anchor is None or anchor.calculated_volume_m3 is None:
                result[row.tank_id] = ReceivingTankArrivalProjection(row.tank_id, None, "UNAVAILABLE", "Forecast anchor has no observed physical volume.")
            elif anchor.calculated_mass_mt is None or anchor.calculated_mass_mt <= 0:
                result[row.tank_id] = ReceivingTankArrivalProjection(row.tank_id, None, "UNAVAILABLE", "Forecast anchor mass is invalid for volume conversion.")
            elif forecast.predicted_mass_mt <= 0:
                result[row.tank_id] = ReceivingTankArrivalProjection(row.tank_id, 0.0, "ESTIMATED", "Tank predicted depleted before arrival.")
            else:
                result[row.tank_id] = ReceivingTankArrivalProjection(row.tank_id, forecast.predicted_mass_mt * anchor.calculated_volume_m3 / anchor.calculated_mass_mt, "ESTIMATED", forecast.issue)
        return result

    def has_receiving_tank_plan(self, plan: PlannedBunker) -> bool:
        return self._repository.has_receiving_tank_plan(plan)
    def list_plan_statuses(self, vessel_id: int, current_events: list[ScheduleEvent]) -> list[BunkerPlanStatus]:
        current_by_sequence = {
            event.sequence_number: event
            for event in current_events
        }
        statuses: list[BunkerPlanStatus] = []
        for plan in self._repository.list_plans(vessel_id):
            current_event = current_by_sequence.get(plan.sequence_number)
            current_arrival_snapshot = current_event.effective_arrival_at.isoformat(timespec="minutes") if current_event else None
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
            if limit is not None and limit.max_lift_mt is None and quantity.quantity_mt > 0:
                raise ValueError(f"Planned {quantity.fuel_type} lift cannot be validated because Max Lift is unavailable.")
            if (
                limit is not None
                and limit.max_lift_mt is not None
                and round(quantity.quantity_mt, 2) > round(limit.max_lift_mt, 2)
            ):
                raise ValueError(f"Planned {quantity.fuel_type} lift exceeds calculated Max Lift.")


def _arrival_utc(arrival_snapshot: str | None) -> datetime | None:
    if not arrival_snapshot:
        return None
    try:
        value = datetime.fromisoformat(arrival_snapshot)
    except ValueError:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
