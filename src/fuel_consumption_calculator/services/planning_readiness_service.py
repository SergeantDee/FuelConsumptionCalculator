from __future__ import annotations

from dataclasses import dataclass

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.voyage_stages import (
    STAGE_ARRIVAL_MANEUVERING,
    STAGE_DEPARTURE_MANEUVERING,
    STAGE_PORT_STAY,
    STAGE_SEA_PASSAGE,
    build_voyage_stage_timeline,
)


VESSEL_CONFIGURED = "VESSEL_CONFIGURED"
PERFORMANCE_CONFIGURED = "PERFORMANCE_CONFIGURED"
INITIAL_FUEL_STATE_CONFIGURED = "INITIAL_FUEL_STATE_CONFIGURED"
AGGREGATE_ROB_AVAILABLE = "AGGREGATE_ROB_AVAILABLE"
TANK_CONFIGURATION_AVAILABLE = "TANK_CONFIGURATION_AVAILABLE"
TANK_PHYSICAL_ROB_AVAILABLE = "TANK_PHYSICAL_ROB_AVAILABLE"
SCHEDULE_AVAILABLE = "SCHEDULE_AVAILABLE"
VOYAGE_PROJECTION_AVAILABLE = "VOYAGE_PROJECTION_AVAILABLE"

SETUP_REQUIRED_KEYS = (
    VESSEL_CONFIGURED,
    PERFORMANCE_CONFIGURED,
    INITIAL_FUEL_STATE_CONFIGURED,
    AGGREGATE_ROB_AVAILABLE,
    SCHEDULE_AVAILABLE,
)


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    key: str
    available: bool
    required: bool
    label: str
    reason: str | None = None
    missing_inputs: tuple[str, ...] = ()
    status: str | None = None


@dataclass(frozen=True, slots=True)
class PlanningReadiness:
    checks: tuple[ReadinessCheck, ...]
    first_blocking_stage: str | None = None
    blocking_reason: str | None = None
    missing_inputs: tuple[str, ...] = ()
    calculation_available_until: str | None = None

    def check(self, key: str) -> ReadinessCheck:
        return next(item for item in self.checks if item.key == key)

    def is_available(self, key: str) -> bool:
        return self.check(key).available

    @property
    def ready(self) -> bool:
        return all(item.available for item in self.checks if item.required)

    @property
    def setup_complete(self) -> bool:
        """Initialization status, intentionally separate from voyage-stage readiness."""
        return all(self.is_available(key) for key in SETUP_REQUIRED_KEYS)

    @property
    def setup_blocking_reason(self) -> str | None:
        for key in SETUP_REQUIRED_KEYS:
            check = self.check(key)
            if not check.available:
                return check.reason or check.label
        return None


class PlanningReadinessService:
    """Derive planning capability from persisted data and authoritative engine results."""

    def __init__(
        self,
        vessel_service,
        schedule_service,
        consumption_service,
        voyage_service,
        rob_service,
        fuel_tank_service,
    ) -> None:
        self._vessel_service = vessel_service
        self._schedule_service = schedule_service
        self._consumption_service = consumption_service
        self._voyage_service = voyage_service
        self._rob_service = rob_service
        self._fuel_tank_service = fuel_tank_service

    def evaluate(self) -> PlanningReadiness:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            return self._without_vessel()

        vessel_id = vessel.id
        fuel_state = self._voyage_service.load_initial_fuel_state(vessel_id)
        performance_missing = self._performance_missing(vessel_id)
        performance_available = not performance_missing
        actual_observations = self._voyage_service.list_actual_rob_observations(vessel_id)
        aggregate_rob = bool(actual_observations) or self._rob_service.has_starting_rob(vessel_id)
        tanks = self._fuel_tank_service.list_tanks(vessel_id)
        applicable_tanks = [tank for tank in tanks if tank.tank_type == "BUNKER"]
        physical_missing = tuple(
            tank.name
            for tank in applicable_tanks
            if self._fuel_tank_service.get_latest_physical_mass_anchor(tank.id) is None
        )
        physical_known = len(applicable_tanks) - len(physical_missing)
        if applicable_tanks and physical_known == len(applicable_tanks):
            physical_state = "COMPLETE"
            physical_label = (
                f"Tank physical ROB complete — {physical_known} of "
                f"{len(applicable_tanks)} applicable tanks known"
            )
        elif physical_known:
            physical_state = "PARTIAL"
            physical_label = (
                f"Tank physical ROB partial — {physical_known} of "
                f"{len(applicable_tanks)} applicable tanks known"
            )
        else:
            physical_state = "UNAVAILABLE"
            physical_label = "Tank physical ROB unavailable — no physical tank mass recorded"
        tank_physical = physical_state == "COMPLETE"
        events = self._schedule_service.list_events(vessel_id)
        schedule_available = bool(events)

        first_stage = None
        blocking_reason = None
        voyage_missing: tuple[str, ...] = ()
        available_until = None
        projection_available = False
        if not schedule_available:
            blocking_reason = "No schedule is available. Update or enter the schedule."
            voyage_missing = ("schedule",)
        else:
            try:
                timeline = self._schedule_service.get_timeline(vessel_id)
                if timeline.issues:
                    blocking_reason = timeline.issues[0].message
                    voyage_missing = ("valid schedule chronology",)
                else:
                    profile = self._consumption_service.load_profile(vessel_id)
                    plan = self._voyage_service.calculate_plan(vessel_id, events, profile)
                    result = self._voyage_service.calculate_consumption_for_plan(
                        events=events, timeline=timeline, plan=plan, profile=profile,
                    )
                    stages = build_voyage_stage_timeline(
                        events,
                        plan,
                        self._rob_service.load_starting_rob(vessel_id),
                        port_breakdowns=result.port_breakdowns,
                        rob_observations=actual_observations,
                    ).stages
                    incomplete = next(
                        (
                            stage for stage in stages
                            if stage.total_consumption_mt is None
                            or any(value is None for value in stage.rob.end_mt.values())
                        ),
                        None,
                    )
                    if incomplete is not None:
                        index = stages.index(incomplete)
                        available_until = stages[index - 1].title if index else None
                        first_stage = incomplete.title
                        if incomplete.total_consumption_mt is None:
                            blocking_reason, voyage_missing = self._stage_reason(
                                incomplete, plan.energy_config, fuel_state,
                            )
                        else:
                            blocking_reason = "Predicted ROB is unavailable because no aggregate ROB anchor applies before this stage."
                            voyage_missing = ("aggregate ROB anchor",)
                    elif not aggregate_rob:
                        blocking_reason = "Aggregate ROB anchor is missing. Enter Projection Starting ROB or an Actual ROB observation."
                        voyage_missing = ("aggregate ROB anchor",)
                        available_until = stages[-1].title if stages else None
                    else:
                        projection_available = bool(stages)
                        available_until = stages[-1].title if stages else None
            except Exception as exc:
                blocking_reason = f"Voyage projection could not be evaluated: {exc}"
                voyage_missing = ("valid voyage inputs",)

        checks = (
            ReadinessCheck(VESSEL_CONFIGURED, True, True, "Vessel configured"),
            ReadinessCheck(
                PERFORMANCE_CONFIGURED, performance_available, True,
                "Performance model configured",
                None if performance_available else "Technical performance inputs are incomplete.",
                performance_missing,
            ),
            ReadinessCheck(
                INITIAL_FUEL_STATE_CONFIGURED, fuel_state is not None, True,
                "Initial machinery fuel state configured",
                None if fuel_state else "Select the current fuel for Main Engine, Generators, and Auxiliary Boiler.",
                () if fuel_state else ("Main Engine fuel", "Generator fuel", "Auxiliary Boiler fuel"),
            ),
            ReadinessCheck(
                AGGREGATE_ROB_AVAILABLE, aggregate_rob, True, "Aggregate ROB anchor available",
                None if aggregate_rob else "Enter Projection Starting ROB or an Actual ROB observation.",
                () if aggregate_rob else ("aggregate ROB anchor",),
            ),
            ReadinessCheck(
                TANK_CONFIGURATION_AVAILABLE, bool(tanks), False, "Tank set configured",
                None if tanks else "Configure the vessel tank set for physical tank forecasting.",
                () if tanks else ("fuel tank configuration",),
            ),
            ReadinessCheck(
                TANK_PHYSICAL_ROB_AVAILABLE, tank_physical, False, physical_label,
                None,
                physical_missing if applicable_tanks else ("applicable bunker/storage tank configuration",),
                physical_state,
            ),
            ReadinessCheck(
                SCHEDULE_AVAILABLE, schedule_available, True, "Schedule available",
                None if schedule_available else "Update or enter a schedule.",
                () if schedule_available else ("schedule",),
            ),
            ReadinessCheck(
                VOYAGE_PROJECTION_AVAILABLE, projection_available, True,
                "Voyage projection available", blocking_reason, voyage_missing,
            ),
        )
        return PlanningReadiness(
            checks=checks,
            first_blocking_stage=first_stage,
            blocking_reason=blocking_reason,
            missing_inputs=voyage_missing,
            calculation_available_until=available_until,
        )

    def _performance_missing(self, vessel_id: int) -> tuple[str, ...]:
        config = self._voyage_service.load_energy_config(vessel_id)
        missing: list[str] = []
        if not self._voyage_service.has_energy_config(vessel_id):
            missing.append("saved vessel performance profile")
        if config.mcr_power_kw <= 0 or config.speed_rpm_factor <= 0 or config.power_coefficient <= 0:
            missing.append("Main Engine performance / MCR")
        if not self._voyage_service.list_main_engine_sfoc_points(vessel_id):
            missing.append("Main Engine SFOC curve")
        if config.generator_rated_kw <= 0:
            missing.append("DG rated power")
        if config.port_running_generators <= 0:
            missing.append("port DG count")
        if config.sea_running_generators <= 0:
            missing.append("sea DG count")
        if not self._voyage_service.list_generator_sfoc_points(vessel_id):
            missing.append("DG SFOC curve")
        if any(value is None for value in (
            config.maneuvering_main_engine_mt_per_hour,
            config.maneuvering_generators_mt_per_hour,
            config.maneuvering_aux_boiler_mt_per_hour,
        )):
            missing.append("maneuvering rates")
        return tuple(dict.fromkeys(missing))

    @staticmethod
    def _stage_reason(stage, config, fuel_state) -> tuple[str, tuple[str, ...]]:
        if stage.stage_type == STAGE_PORT_STAY and stage.port_breakdown:
            warnings = tuple(_clean_warning(item) for item in stage.port_breakdown.warnings)
            if warnings:
                return warnings[0], warnings
        if stage.stage_type in (STAGE_DEPARTURE_MANEUVERING, STAGE_ARRIVAL_MANEUVERING):
            missing = []
            if config is None or any(getattr(config, key) is None for key in (
                "maneuvering_main_engine_mt_per_hour",
                "maneuvering_generators_mt_per_hour",
                "maneuvering_aux_boiler_mt_per_hour",
            )):
                missing.append("maneuvering fuel rates")
            if fuel_state is None:
                missing.append("initial machinery fuel state")
            return "Missing required maneuvering inputs: " + ", ".join(missing), tuple(missing)
        if stage.stage_type == STAGE_SEA_PASSAGE:
            warnings = tuple(_clean_warning(item) for item in (stage.leg.warnings if stage.leg else ()))
            relevant = tuple(item for item in warnings if "incomplete" in item.lower() or "missing" in item.lower() or "unavailable" in item.lower())
            if relevant:
                return relevant[0], relevant
            return "Distance, speed, or performance basis is unavailable.", ("sea passage calculation inputs",)
        return "Required operational inputs are unavailable.", ("operational inputs",)

    @staticmethod
    def _without_vessel() -> PlanningReadiness:
        labels = (
            (VESSEL_CONFIGURED, "Vessel configured", True),
            (PERFORMANCE_CONFIGURED, "Performance model configured", True),
            (INITIAL_FUEL_STATE_CONFIGURED, "Initial machinery fuel state configured", True),
            (AGGREGATE_ROB_AVAILABLE, "Aggregate ROB anchor available", True),
            (TANK_CONFIGURATION_AVAILABLE, "Tank set configured", False),
            (TANK_PHYSICAL_ROB_AVAILABLE, "Initial physical tank ROB complete", False),
            (SCHEDULE_AVAILABLE, "Schedule available", True),
            (VOYAGE_PROJECTION_AVAILABLE, "Voyage projection available", True),
        )
        checks = tuple(
            ReadinessCheck(key, False, required, label, "Configure vessel details first.", ("vessel details",))
            for key, label, required in labels
        )
        return PlanningReadiness(checks, blocking_reason="Configure vessel details first.", missing_inputs=("vessel details",))


def _clean_warning(value: str) -> str:
    text = value.strip().rstrip(".")
    prefix = "Calculation incomplete: "
    return text[len(prefix):] if text.startswith(prefix) else text
