from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.rob import StartingROB
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.voyage import ActualROBObservation, CalculatedVoyageLeg, FuelChangeoverEvent, PortEnergyBreakdown, VoyagePlan


STAGE_PORT_STAY = "PORT_STAY"
STAGE_DEPARTURE_MANEUVERING = "DEPARTURE_MANEUVERING"
STAGE_SEA_PASSAGE = "SEA_PASSAGE"
STAGE_ARRIVAL_MANEUVERING = "ARRIVAL_MANEUVERING"

STATUS_COMPLETED = "COMPLETED"
STATUS_CURRENT = "CURRENT"
STATUS_PLANNED = "PLANNED"


@dataclass(frozen=True, slots=True)
class StageROB:
    start_mt: dict[str, float | None]
    end_mt: dict[str, float | None]


@dataclass(frozen=True, slots=True)
class OperationalStage:
    key: str
    stage_type: str
    title: str
    subtitle: str
    status: str
    start_utc: datetime | None
    end_utc: datetime | None
    event: ScheduleEvent | None
    leg: CalculatedVoyageLeg | None
    incoming_leg: CalculatedVoyageLeg | None
    consumption_mt: dict[str, float | None]
    rob: StageROB
    changeovers: tuple[FuelChangeoverEvent, ...] = ()
    port_breakdown: PortEnergyBreakdown | None = None

    @property
    def total_consumption_mt(self) -> float | None:
        values = [self.consumption_mt.get(fuel_type) for fuel_type in FUEL_TYPES]
        if any(value is None for value in values):
            return None
        return sum(float(value or 0.0) for value in values)


@dataclass(frozen=True, slots=True)
class VoyageStageTimeline:
    stages: list[OperationalStage]
    current_stage: OperationalStage | None
    next_port: str | None
    current_predicted_rob_mt: dict[str, float | None]


def build_voyage_stage_timeline(
    events: list[ScheduleEvent],
    plan: VoyagePlan,
    starting_rob: StartingROB,
    *,
    port_breakdowns: dict[int, PortEnergyBreakdown] | None = None,
    now_utc: datetime | None = None,
    rob_observations: list[ActualROBObservation] | tuple[ActualROBObservation, ...] = (),
    port_bunker_additions: dict[int, dict[str, float]] | None = None,
) -> VoyageStageTimeline:
    ordered_events = sorted(events, key=lambda event: (event.sequence_number, event.effective_arrival_at, event.id))
    incoming_by_event = {leg.leg.destination_event_id: leg for leg in plan.legs}
    outgoing_by_event = {leg.leg.origin_event_id: leg for leg in plan.legs}
    port_breakdowns = port_breakdowns or {}
    changeovers = tuple(sorted(plan.fuel_changeovers, key=lambda event: _instant(event.effective_at_utc) or datetime.min))
    observations = tuple(sorted(rob_observations, key=lambda observation: _instant(observation.effective_at_utc) or datetime.min))
    port_bunker_additions = port_bunker_additions or {}
    applied_observation_indexes: set[int] = set()
    cursor_rob: dict[str, float | None] = {fuel_type: starting_rob.quantity_for(fuel_type) for fuel_type in FUEL_TYPES}
    stages: list[OperationalStage] = []
    now = _instant(now_utc or datetime.now(timezone.utc))

    for event in ordered_events:
        outgoing = outgoing_by_event.get(event.id)
        incoming = incoming_by_event.get(event.id)
        port_breakdown = port_breakdowns.get(event.id)
        port_consumption = port_breakdown.total_consumed_mt if port_breakdown else _empty_totals()
        port_start = _instant(incoming.effective_berth_arrival if incoming else event.effective_arrival_at)
        port_end = _instant(outgoing.effective_berth_departure if outgoing else event.effective_departure_at)
        stage = _stage(
            key=f"port-{event.id}",
            stage_type=STAGE_PORT_STAY,
            title=f"{event.port} PORT STAY",
            subtitle="ARRIVAL BERTH -> DEPARTURE BERTH",
            status=_port_status(incoming, outgoing, port_start, port_end, now),
            start_utc=port_start,
            end_utc=port_end,
            event=event,
            leg=outgoing,
            incoming_leg=incoming,
            consumption=port_consumption,
            cursor_rob=cursor_rob,
            addition=port_bunker_additions.get(event.id),
            observations=observations,
            applied_observation_indexes=applied_observation_indexes,
            changeovers=_changeovers_between(changeovers, port_start, port_end),
            port_breakdown=port_breakdown,
        )
        stages.append(stage)

        if outgoing is None:
            continue

        stage = _stage(
            key=f"departure-{outgoing.leg.origin_event_id}-{outgoing.leg.destination_event_id}",
            stage_type=STAGE_DEPARTURE_MANEUVERING,
            title=f"{outgoing.leg.origin_port} BERTH -> PILOT OFF",
            subtitle="DEPARTURE MANEUVERING",
            status=_actual_status(
                has_started=outgoing.leg.override.actual_berth_departure is not None if outgoing.leg.override else False,
                has_ended=outgoing.leg.override.actual_pilot_off is not None if outgoing.leg.override else False,
                start_utc=_instant(outgoing.effective_berth_departure),
                end_utc=_instant(outgoing.pilot_off),
                now_utc=now,
            ),
            start_utc=_instant(outgoing.effective_berth_departure),
            end_utc=_instant(outgoing.pilot_off),
            event=event,
            leg=outgoing,
            incoming_leg=None,
            consumption=outgoing.departure_maneuvering_consumed_mt,
            cursor_rob=cursor_rob,
            addition=None,
            observations=observations,
            applied_observation_indexes=applied_observation_indexes,
            changeovers=_changeovers_between(changeovers, outgoing.effective_berth_departure, outgoing.pilot_off),
        )
        stages.append(stage)

        stage = _stage(
            key=f"sea-{outgoing.leg.origin_event_id}-{outgoing.leg.destination_event_id}",
            stage_type=STAGE_SEA_PASSAGE,
            title=f"{outgoing.leg.origin_port} -> {outgoing.leg.destination_port}",
            subtitle="PILOT OFF -> PILOT ON / SEA PASSAGE",
            status=_actual_status(
                has_started=outgoing.leg.override.actual_pilot_off is not None if outgoing.leg.override else False,
                has_ended=outgoing.leg.override.actual_pilot_on is not None if outgoing.leg.override else False,
                start_utc=_instant(outgoing.pilot_off),
                end_utc=_instant(outgoing.pilot_on),
                now_utc=now,
            ),
            start_utc=_instant(outgoing.pilot_off),
            end_utc=_instant(outgoing.pilot_on),
            event=None,
            leg=outgoing,
            incoming_leg=None,
            consumption=outgoing.sea_consumed_mt,
            cursor_rob=cursor_rob,
            addition=None,
            observations=observations,
            applied_observation_indexes=applied_observation_indexes,
            changeovers=_changeovers_between(changeovers, outgoing.pilot_off, outgoing.pilot_on),
        )
        stages.append(stage)

        stage = _stage(
            key=f"arrival-{outgoing.leg.origin_event_id}-{outgoing.leg.destination_event_id}",
            stage_type=STAGE_ARRIVAL_MANEUVERING,
            title=f"{outgoing.leg.destination_port} PILOT ON -> BERTH",
            subtitle="ARRIVAL MANEUVERING",
            status=_actual_status(
                has_started=outgoing.leg.override.actual_pilot_on is not None if outgoing.leg.override else False,
                has_ended=outgoing.leg.override.actual_berth_arrival is not None if outgoing.leg.override else False,
                start_utc=_instant(outgoing.pilot_on),
                end_utc=_instant(outgoing.effective_berth_arrival),
                now_utc=now,
            ),
            start_utc=_instant(outgoing.pilot_on),
            end_utc=_instant(outgoing.effective_berth_arrival),
            event=next((candidate for candidate in ordered_events if candidate.id == outgoing.leg.destination_event_id), None),
            leg=outgoing,
            incoming_leg=None,
            consumption=outgoing.arrival_maneuvering_consumed_mt,
            cursor_rob=cursor_rob,
            addition=None,
            observations=observations,
            applied_observation_indexes=applied_observation_indexes,
            changeovers=_changeovers_between(changeovers, outgoing.pilot_on, outgoing.effective_berth_arrival),
        )
        stages.append(stage)

    current_stage = next((stage for stage in stages if stage.status == STATUS_CURRENT), None)
    pre_voyage = _is_before_first_stage(stages, now)
    next_port = _next_port(current_stage, ordered_events, plan.legs)
    return VoyageStageTimeline(
        stages=stages,
        current_stage=current_stage,
        next_port=next_port,
        current_predicted_rob_mt=dict(stages[0].rob.start_mt if pre_voyage else (current_stage.rob.start_mt if current_stage else cursor_rob)),
    )


def _stage(
    *,
    key: str,
    stage_type: str,
    title: str,
    subtitle: str,
    status: str,
    start_utc,
    end_utc,
    event: ScheduleEvent | None,
    leg: CalculatedVoyageLeg | None,
    incoming_leg: CalculatedVoyageLeg | None,
    consumption: dict[str, float | None],
    cursor_rob: dict[str, float | None],
    addition: dict[str, float] | None,
    observations: tuple[ActualROBObservation, ...],
    applied_observation_indexes: set[int],
    changeovers: tuple[FuelChangeoverEvent, ...],
    port_breakdown: PortEnergyBreakdown | None = None,
) -> OperationalStage:
    normalized_start = _instant(start_utc)
    normalized_end = _instant(end_utc)
    _apply_observations_through(cursor_rob, observations, applied_observation_indexes, normalized_start)
    start_rob = dict(cursor_rob)
    if addition is not None:
        for fuel_type in FUEL_TYPES:
            if cursor_rob[fuel_type] is not None:
                cursor_rob[fuel_type] = float(cursor_rob[fuel_type]) + float(addition.get(fuel_type, 0.0))
    normalized_consumption = {fuel_type: consumption.get(fuel_type, 0.0) for fuel_type in FUEL_TYPES}
    _apply_consumption_with_observations(
        cursor_rob,
        normalized_consumption,
        normalized_start,
        normalized_end,
        observations,
        applied_observation_indexes,
    )
    return OperationalStage(
        key=key,
        stage_type=stage_type,
        title=title,
        subtitle=subtitle,
        status=status,
        start_utc=_instant(start_utc),
        end_utc=_instant(end_utc),
        event=event,
        leg=leg,
        incoming_leg=incoming_leg,
        consumption_mt=normalized_consumption,
        rob=StageROB(start_mt=start_rob, end_mt=dict(cursor_rob)),
        changeovers=changeovers,
        port_breakdown=port_breakdown,
    )


def _apply_consumption_with_observations(
    cursor_rob: dict[str, float | None],
    consumption: dict[str, float | None],
    start_utc: datetime | None,
    end_utc: datetime | None,
    observations: tuple[ActualROBObservation, ...],
    applied_observation_indexes: set[int],
) -> None:
    if any(value is None for value in consumption.values()):
        exact_end_observation: ActualROBObservation | None = None
        for index, observation in enumerate(observations):
            if index in applied_observation_indexes:
                continue
            obs_time = _instant(observation.effective_at_utc)
            if obs_time is None or start_utc is None or end_utc is None or not (start_utc < obs_time <= end_utc):
                continue
            applied_observation_indexes.add(index)
            if obs_time == end_utc:
                exact_end_observation = observation
        if exact_end_observation is not None:
            for fuel_type in FUEL_TYPES:
                cursor_rob[fuel_type] = exact_end_observation.quantity_for(fuel_type)
            return
        for fuel_type in FUEL_TYPES:
            cursor_rob[fuel_type] = None
        return
    if start_utc is None or end_utc is None or end_utc <= start_utc:
        for fuel_type in FUEL_TYPES:
            cursor_rob[fuel_type] = _subtract_optional(cursor_rob[fuel_type], consumption[fuel_type])
        return
    stage_hours = (end_utc - start_utc).total_seconds() / 3600
    cursor = start_utc
    for index, observation in enumerate(observations):
        if index in applied_observation_indexes:
            continue
        obs_time = _instant(observation.effective_at_utc)
        if obs_time is None or not (start_utc < obs_time <= end_utc):
            continue
        applied_observation_indexes.add(index)
        elapsed = (obs_time - cursor).total_seconds() / 3600
        fraction = max(0.0, elapsed / stage_hours)
        for fuel_type in FUEL_TYPES:
            cursor_rob[fuel_type] = _subtract_optional(cursor_rob[fuel_type], consumption[fuel_type] * fraction)
            cursor_rob[fuel_type] = observation.quantity_for(fuel_type)
        cursor = obs_time
    elapsed = (end_utc - cursor).total_seconds() / 3600
    fraction = max(0.0, elapsed / stage_hours)
    for fuel_type in FUEL_TYPES:
        cursor_rob[fuel_type] = _subtract_optional(cursor_rob[fuel_type], consumption[fuel_type] * fraction)


def _apply_observations_through(
    cursor_rob: dict[str, float | None],
    observations: tuple[ActualROBObservation, ...],
    applied_observation_indexes: set[int],
    through_utc: datetime | None,
) -> None:
    if through_utc is None:
        return
    for index, observation in enumerate(observations):
        if index in applied_observation_indexes:
            continue
        obs_time = _instant(observation.effective_at_utc)
        if obs_time is None or obs_time > through_utc:
            continue
        for fuel_type in FUEL_TYPES:
            cursor_rob[fuel_type] = observation.quantity_for(fuel_type)
        applied_observation_indexes.add(index)


def _port_status(
    incoming: CalculatedVoyageLeg | None,
    outgoing: CalculatedVoyageLeg | None,
    start_utc: datetime | None,
    end_utc: datetime | None,
    now_utc: datetime | None,
) -> str:
    arrived = incoming.leg.override.actual_berth_arrival is not None if incoming and incoming.leg.override else False
    departed = outgoing.leg.override.actual_berth_departure is not None if outgoing and outgoing.leg.override else False
    if departed:
        return STATUS_COMPLETED
    if arrived:
        return STATUS_CURRENT
    return _scheduled_status(start_utc, end_utc, now_utc)


def _actual_status(
    *,
    has_started: bool,
    has_ended: bool,
    start_utc: datetime | None,
    end_utc: datetime | None,
    now_utc: datetime | None,
) -> str:
    if has_ended:
        return STATUS_COMPLETED
    if has_started:
        return STATUS_CURRENT
    return _scheduled_status(start_utc, end_utc, now_utc)


def _scheduled_status(start_utc: datetime | None, end_utc: datetime | None, now_utc: datetime | None) -> str:
    if start_utc is None or end_utc is None or now_utc is None:
        return STATUS_PLANNED
    if end_utc <= now_utc:
        return STATUS_COMPLETED
    if start_utc <= now_utc < end_utc:
        return STATUS_CURRENT
    return STATUS_PLANNED


def _changeovers_between(
    changeovers: tuple[FuelChangeoverEvent, ...],
    start_utc,
    end_utc,
) -> tuple[FuelChangeoverEvent, ...]:
    start = _instant(start_utc)
    end = _instant(end_utc)
    if start is None or end is None:
        return ()
    return tuple(changeover for changeover in changeovers if start <= (_instant(changeover.effective_at_utc) or datetime.min) <= end)


def _next_port(current_stage: OperationalStage | None, events: list[ScheduleEvent], legs: list[CalculatedVoyageLeg]) -> str | None:
    if current_stage is None:
        return events[0].port if events else None
    if current_stage.leg is not None:
        if current_stage.stage_type == STAGE_ARRIVAL_MANEUVERING:
            return current_stage.leg.leg.destination_port
        return current_stage.leg.leg.destination_port
    current_index = next((index for index, event in enumerate(events) if current_stage.event and event.id == current_stage.event.id), None)
    if current_index is not None and current_index + 1 < len(events):
        return events[current_index + 1].port
    return legs[0].leg.destination_port if legs else None


def _is_before_first_stage(stages: list[OperationalStage], now_utc: datetime | None) -> bool:
    if not stages or now_utc is None:
        return False
    first_start = next((_instant(stage.start_utc) for stage in stages if stage.start_utc is not None), None)
    return first_start is not None and now_utc < first_start


def _instant(value) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _empty_totals() -> dict[str, float]:
    return {fuel_type: 0.0 for fuel_type in FUEL_TYPES}


def _subtract_optional(value: float | None, consumption: float | None) -> float | None:
    if value is None or consumption is None:
        return None
    return value - consumption
