from __future__ import annotations

from datetime import timedelta

from fuel_consumption_calculator.calculations.consumption_engine import EventFuelConsumption, ScheduleFuelConsumption
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES, ConsumptionProfile
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.schedule_timeline import ScheduleTimeline
from fuel_consumption_calculator.domain.voyage import (
    CalculatedVoyageLeg,
    FuelChangeoverEvent,
    GeneratorSfocPoint,
    MachineryFuelState,
    PortEnergyBreakdown,
    SpeedConsumptionPoint,
    VesselEnergyConfig,
    VoyageLeg,
    VoyagePlan,
    empty_fuel_totals,
)


def calculate_voyage_plan(
    legs: list[VoyageLeg],
    profile: ConsumptionProfile,
    speed_points: list[SpeedConsumptionPoint],
    energy_config: VesselEnergyConfig | None = None,
    generator_sfoc_points: list[GeneratorSfocPoint] | None = None,
    initial_fuel_state: MachineryFuelState | None = None,
    fuel_changeovers: list[FuelChangeoverEvent] | None = None,
) -> VoyagePlan:
    calculated_legs: list[CalculatedVoyageLeg] = []
    warnings: list[str] = []
    ordered_points = sorted(speed_points, key=lambda point: point.speed_knots)
    ordered_sfoc_points = sorted(generator_sfoc_points or [], key=lambda point: point.load_percent)
    config = energy_config or VesselEnergyConfig(vessel_id=legs[0].vessel_id if legs else 0)
    active_fuel_state = initial_fuel_state
    changeovers = sorted(fuel_changeovers or [], key=lambda event: event.effective_at_utc)

    for leg in legs:
        override = leg.override
        dep_pilotage_hours = _effective_float(
            override.departure_pilotage_hours if override else None,
            leg.route.departure_pilotage_hours,
        )
        arr_pilotage_hours = _effective_float(
            override.arrival_pilotage_hours if override else None,
            leg.route.arrival_pilotage_hours,
        )
        sea_distance_nm = _effective_float(
            override.sea_distance_nm if override else None,
            leg.route.sea_distance_nm,
        )
        berth_departure = (override.actual_berth_departure if override and override.actual_berth_departure else None) or leg.scheduled_berth_departure
        berth_arrival = (override.actual_berth_arrival if override and override.actual_berth_arrival else None) or leg.scheduled_berth_arrival
        pilot_off = (override.actual_pilot_off if override and override.actual_pilot_off else None) or (berth_departure + timedelta(hours=dep_pilotage_hours))
        pilot_on = (override.actual_pilot_on if override and override.actual_pilot_on else None) or (berth_arrival - timedelta(hours=arr_pilotage_hours))
        sea_hours = (pilot_on - pilot_off).total_seconds() / 3600
        leg_warnings: list[str] = []
        required_speed = None
        if sea_hours <= 0:
            leg_warnings.append(f"{leg.origin_port} -> {leg.destination_port} has no available sea time.")
            sea_hours = 0.0
        elif sea_distance_nm > 0:
            required_speed = sea_distance_nm / sea_hours

        departure_maneuvering = {
            fuel_type: _consume(dep_pilotage_hours, profile.rate_for("MANEUVERING", fuel_type))
            for fuel_type in FUEL_TYPES
        }
        arrival_maneuvering = {
            fuel_type: _consume(arr_pilotage_hours, profile.rate_for("MANEUVERING", fuel_type))
            for fuel_type in FUEL_TYPES
        }
        speed_perf = interpolate_speed_performance(required_speed, ordered_points) if required_speed is not None else None
        predicted_me_load = speed_perf["main_engine_load_percent"] if speed_perf else None
        sea_breakdown = _sea_consumption(
            sea_hours,
            required_speed,
            profile,
            ordered_points,
            config,
            ordered_sfoc_points,
            leg.override.departure_reefers if leg.override and leg.override.departure_reefers is not None else 0.0,
            predicted_me_load,
            leg.override.use_egb if leg.override else False,
            leg_warnings,
            active_fuel_state,
            changeovers,
            pilot_off,
            pilot_on,
        )
        sea_consumed = sea_breakdown["total"]
        total = {
            fuel_type: departure_maneuvering[fuel_type] + sea_consumed[fuel_type] + arrival_maneuvering[fuel_type]
            for fuel_type in FUEL_TYPES
        }
        warnings.extend(leg_warnings)
        calculated_legs.append(
            CalculatedVoyageLeg(
                leg=leg,
                effective_berth_departure=berth_departure,
                pilot_off=pilot_off,
                pilot_on=pilot_on,
                effective_berth_arrival=berth_arrival,
                departure_pilotage_hours=dep_pilotage_hours,
                sea_hours=sea_hours,
                arrival_pilotage_hours=arr_pilotage_hours,
                required_speed_knots=required_speed,
                departure_maneuvering_consumed_mt=departure_maneuvering,
                sea_consumed_mt=sea_consumed,
                arrival_maneuvering_consumed_mt=arrival_maneuvering,
                total_pre_arrival_consumed_mt=total,
                predicted_me_load_percent=predicted_me_load,
                egb_available=(predicted_me_load is not None and predicted_me_load >= 25.0),
                egb_used=sea_breakdown["egb_used"],
                sea_generator_consumed_mt=sea_breakdown["generator"],
                sea_boiler_consumed_mt=sea_breakdown["boiler"],
                sea_total_electrical_load_kw=sea_breakdown["total_load_kw"],
                sea_generator_load_percent=sea_breakdown["generator_load_percent"],
                sea_generator_sfoc_g_per_kwh=sea_breakdown["generator_sfoc"],
                sea_calculation_mode=sea_breakdown["mode"],
                warnings=tuple(leg_warnings),
            )
        )

    return VoyagePlan(
        legs=calculated_legs,
        warnings=warnings,
        port_breakdowns={},
        energy_config=config,
        generator_sfoc_points=tuple(ordered_sfoc_points),
        initial_fuel_state=active_fuel_state,
        fuel_changeovers=tuple(changeovers),
    )


def calculate_consumption_with_voyage(
    timeline: ScheduleTimeline,
    events: list[ScheduleEvent],
    plan: VoyagePlan,
    profile: ConsumptionProfile,
) -> ScheduleFuelConsumption:
    if timeline.issues:
        raise ValueError(f"Cannot calculate consumption while schedule chronology is invalid: {timeline.issues[0].message}")

    leg_consumption_by_destination = {
        calculated_leg.leg.destination_event_id: calculated_leg.total_pre_arrival_consumed_mt
        for calculated_leg in plan.legs
    }
    leg_hours_by_destination = {
        calculated_leg.leg.destination_event_id: (
            calculated_leg.departure_pilotage_hours
            + calculated_leg.sea_hours
            + calculated_leg.arrival_pilotage_hours
        )
        for calculated_leg in plan.legs
    }
    actual_arrivals = {
        calculated_leg.leg.destination_event_id: calculated_leg.effective_berth_arrival
        for calculated_leg in plan.legs
    }
    actual_departures = {
        calculated_leg.leg.origin_event_id: calculated_leg.effective_berth_departure
        for calculated_leg in plan.legs
    }
    timeline_by_event = {row.event.id: row for row in timeline.rows}
    outgoing_leg_by_origin = {calculated_leg.leg.origin_event_id: calculated_leg for calculated_leg in plan.legs}
    rows: list[EventFuelConsumption] = []
    totals = empty_fuel_totals()

    for event in events:
        timeline_row = timeline_by_event.get(event.id)
        sea_consumed = {
            fuel_type: leg_consumption_by_destination.get(event.id, {}).get(fuel_type, 0.0)
            for fuel_type in FUEL_TYPES
        }
        sea_hours = leg_hours_by_destination.get(event.id, timeline_row.interval_from_previous_hours if timeline_row and timeline_row.interval_from_previous_hours else 0.0)
        port_hours = _port_hours(event, actual_arrivals.get(event.id), actual_departures.get(event.id), timeline_row.port_stay_hours if timeline_row else None)
        breakdown = _port_consumption(
            event,
            port_hours,
            outgoing_leg_by_origin.get(event.id),
            profile,
            plan.energy_config or VesselEnergyConfig(vessel_id=event.vessel_id),
            list(plan.generator_sfoc_points),
            plan.initial_fuel_state,
            list(plan.fuel_changeovers),
            event.effective_arrival_at,
            (actual_departures.get(event.id) or event.effective_departure_at),
        )
        port_consumed = breakdown.total_consumed_mt
        consumed = {fuel_type: sea_consumed[fuel_type] + port_consumed[fuel_type] for fuel_type in FUEL_TYPES}
        for fuel_type in FUEL_TYPES:
            totals[fuel_type] += consumed[fuel_type]
        rows.append(
            EventFuelConsumption(
                event_id=event.id,
                sequence_number=event.sequence_number,
                port=event.port,
                sea_hours=max(0.0, sea_hours or 0.0),
                port_hours=max(0.0, port_hours),
                consumed_mt=consumed,
                sea_consumed_mt=sea_consumed,
                port_consumed_mt=port_consumed,
            )
        )
    return ScheduleFuelConsumption(rows=rows, totals_mt=totals)


def interpolate_speed_rates(
    speed_knots: float,
    speed_points: list[SpeedConsumptionPoint],
) -> dict[str, float] | None:
    performance = interpolate_speed_performance(speed_knots, speed_points)
    return None if performance is None else {fuel_type: performance[fuel_type] for fuel_type in FUEL_TYPES}


def interpolate_speed_performance(
    speed_knots: float | None,
    speed_points: list[SpeedConsumptionPoint],
) -> dict[str, float] | None:
    if speed_knots is None:
        return None
    points = sorted(speed_points, key=lambda point: point.speed_knots)
    if not points:
        return None
    if speed_knots < points[0].speed_knots or speed_knots > points[-1].speed_knots:
        return None
    for point in points:
        if abs(point.speed_knots - speed_knots) < 0.0001:
            return {
                **{fuel_type: point.rate_for(fuel_type) for fuel_type in FUEL_TYPES},
                "main_engine_load_percent": point.main_engine_load_percent,
            }
    for left, right in zip(points, points[1:]):
        if left.speed_knots <= speed_knots <= right.speed_knots:
            span = right.speed_knots - left.speed_knots
            ratio = (speed_knots - left.speed_knots) / span if span else 0.0
            interpolated = {
                fuel_type: left.rate_for(fuel_type) + ratio * (right.rate_for(fuel_type) - left.rate_for(fuel_type))
                for fuel_type in FUEL_TYPES
            }
            if left.main_engine_load_percent is not None and right.main_engine_load_percent is not None:
                interpolated["main_engine_load_percent"] = left.main_engine_load_percent + ratio * (right.main_engine_load_percent - left.main_engine_load_percent)
            else:
                interpolated["main_engine_load_percent"] = None
            return interpolated
    return None


def interpolate_generator_sfoc(
    load_percent: float | None,
    sfoc_points: list[GeneratorSfocPoint],
) -> float | None:
    if load_percent is None:
        return None
    points = sorted(sfoc_points, key=lambda point: point.load_percent)
    if not points:
        return None
    if load_percent < points[0].load_percent or load_percent > points[-1].load_percent:
        return None
    for point in points:
        if abs(point.load_percent - load_percent) < 0.0001:
            return point.sfoc_g_per_kwh
    for left, right in zip(points, points[1:]):
        if left.load_percent <= load_percent <= right.load_percent:
            span = right.load_percent - left.load_percent
            ratio = (load_percent - left.load_percent) / span if span else 0.0
            return left.sfoc_g_per_kwh + ratio * (right.sfoc_g_per_kwh - left.sfoc_g_per_kwh)
    return None


def _sea_consumption(
    sea_hours: float,
    speed_knots: float | None,
    profile: ConsumptionProfile,
    speed_points: list[SpeedConsumptionPoint],
    config: VesselEnergyConfig,
    sfoc_points: list[GeneratorSfocPoint],
    departure_reefers: float,
    predicted_me_load: float | None,
    requested_egb: bool,
    warnings: list[str],
    initial_fuel_state: MachineryFuelState | None = None,
    fuel_changeovers: list[FuelChangeoverEvent] | None = None,
    start_utc=None,
    end_utc=None,
) -> dict[str, float]:
    interpolated = interpolate_speed_rates(speed_knots, speed_points) if speed_knots is not None else None
    if speed_knots is not None and speed_points and interpolated is None:
        warnings.append(f"Required speed {speed_knots:.2f} kn is outside configured speed-consumption points; fixed SEA rates were used.")
    rates = interpolated or {fuel_type: profile.rate_for("SEA", fuel_type) for fuel_type in FUEL_TYPES}
    if initial_fuel_state and start_utc and end_utc:
        main_engine = _split_rate_consumption("MAIN_ENGINE", start_utc, end_utc, initial_fuel_state, fuel_changeovers or [], rates)
    else:
        main_engine = {fuel_type: _consume(sea_hours, rates[fuel_type]) for fuel_type in FUEL_TYPES}
    generator = empty_fuel_totals()
    boiler = empty_fuel_totals()
    egb_available = predicted_me_load is not None and predicted_me_load >= 25.0
    egb_used = requested_egb and egb_available
    if requested_egb and not egb_available:
        warnings.append("EGB was selected but is unavailable below 25% predicted ME load; auxiliary boiler was used.")

    total_load_kw = config.sea_base_load_kw + departure_reefers * config.reefer_kw_per_unit
    generator_load_percent = _generator_load_percent(total_load_kw, config.generator_rated_kw, config.sea_running_generators, warnings)
    generator_sfoc = interpolate_generator_sfoc(generator_load_percent, sfoc_points)
    detailed_ready = _energy_config_ready(config) and generator_load_percent is not None and generator_sfoc is not None
    mode = "DETAILED" if detailed_ready else "FALLBACK"
    if detailed_ready:
        if initial_fuel_state and start_utc and end_utc:
            generator = _split_quantity_consumption("GENERATORS", start_utc, end_utc, initial_fuel_state, fuel_changeovers or [], lambda hours: _generator_fuel(total_load_kw, generator_sfoc, hours))
        else:
            generator[config.generator_fuel_type] += _generator_fuel(total_load_kw, generator_sfoc, sea_hours)
        if not egb_used:
            if initial_fuel_state and start_utc and end_utc:
                boiler = _split_quantity_consumption("AUX_BOILER", start_utc, end_utc, initial_fuel_state, fuel_changeovers or [], lambda hours: hours * config.aux_boiler_mt_per_hour)
            else:
                boiler[config.boiler_fuel_type] += sea_hours * config.aux_boiler_mt_per_hour
    elif total_load_kw > 0 or config.aux_boiler_mt_per_hour > 0:
        warnings.append("Detailed sea load configuration is incomplete or out of range; fixed SEA fallback was used.")
    total = {fuel_type: main_engine[fuel_type] + generator[fuel_type] + boiler[fuel_type] for fuel_type in FUEL_TYPES}
    return {
        "total": total,
        "generator": generator,
        "boiler": boiler,
        "total_load_kw": total_load_kw,
        "generator_load_percent": generator_load_percent,
        "generator_sfoc": generator_sfoc,
        "mode": mode,
        "egb_used": egb_used,
    }


def _port_consumption(
    event: ScheduleEvent,
    port_hours: float,
    outgoing_leg: CalculatedVoyageLeg | None,
    profile: ConsumptionProfile,
    config: VesselEnergyConfig,
    sfoc_points: list[GeneratorSfocPoint],
    initial_fuel_state: MachineryFuelState | None = None,
    fuel_changeovers: list[FuelChangeoverEvent] | None = None,
    start_utc=None,
    end_utc=None,
) -> PortEnergyBreakdown:
    reefers = outgoing_leg.leg.override.port_reefers if outgoing_leg and outgoing_leg.leg.override and outgoing_leg.leg.override.port_reefers is not None else 0.0
    total_load_kw = config.port_base_load_kw + reefers * config.reefer_kw_per_unit
    local_warnings: list[str] = []
    generator_load_percent = _generator_load_percent(total_load_kw, config.generator_rated_kw, config.port_running_generators, local_warnings)
    generator_sfoc = interpolate_generator_sfoc(generator_load_percent, sfoc_points)
    generator = empty_fuel_totals()
    boiler = empty_fuel_totals()
    if _energy_config_ready(config) and generator_load_percent is not None and generator_sfoc is not None:
        if initial_fuel_state and start_utc and end_utc:
            generator = _split_quantity_consumption("GENERATORS", start_utc, end_utc, initial_fuel_state, fuel_changeovers or [], lambda hours: _generator_fuel(total_load_kw, generator_sfoc, hours))
            boiler = _split_quantity_consumption("AUX_BOILER", start_utc, end_utc, initial_fuel_state, fuel_changeovers or [], lambda hours: hours * config.aux_boiler_mt_per_hour)
        else:
            generator[config.generator_fuel_type] += _generator_fuel(total_load_kw, generator_sfoc, port_hours)
            boiler[config.boiler_fuel_type] += port_hours * config.aux_boiler_mt_per_hour
        mode = "DETAILED"
    else:
        generator = {fuel_type: _consume(port_hours, profile.rate_for("PORT", fuel_type)) for fuel_type in FUEL_TYPES}
        mode = "FALLBACK"
    total = {fuel_type: generator[fuel_type] + boiler[fuel_type] for fuel_type in FUEL_TYPES}
    return PortEnergyBreakdown(
        event_id=event.id,
        port=event.port,
        port_hours=port_hours,
        reefers=reefers,
        total_electrical_load_kw=total_load_kw,
        generator_load_percent=generator_load_percent,
        generator_sfoc_g_per_kwh=generator_sfoc,
        generator_consumed_mt=generator,
        boiler_consumed_mt=boiler,
        total_consumed_mt=total,
        calculation_mode=mode,
        warnings=tuple(local_warnings),
    )


def _energy_config_ready(config: VesselEnergyConfig) -> bool:
    return (
        config.generator_rated_kw > 0
        and config.port_running_generators > 0
        and config.sea_running_generators > 0
        and config.generator_fuel_type in FUEL_TYPES
        and config.boiler_fuel_type in FUEL_TYPES
    )


def _generator_load_percent(
    total_load_kw: float,
    rated_kw: float,
    running_generators: float,
    warnings: list[str],
) -> float | None:
    if total_load_kw <= 0:
        return 0.0
    capacity = rated_kw * running_generators
    if capacity <= 0:
        warnings.append("Generator count/capacity is zero while electrical load is nonzero.")
        return None
    load_percent = total_load_kw / capacity * 100
    if load_percent > 100:
        warnings.append("Calculated generator load exceeds configured running capacity.")
    return load_percent


def _generator_fuel(total_load_kw: float, sfoc_g_per_kwh: float, hours: float) -> float:
    return total_load_kw * sfoc_g_per_kwh / 1_000_000 * max(0.0, hours)


def _port_hours(event: ScheduleEvent, actual_arrival, actual_departure, fallback: float | None) -> float:
    arrival = actual_arrival or event.effective_arrival_at
    departure = actual_departure or event.effective_departure_at
    if departure is None:
        return max(0.0, fallback or 0.0)
    return max(0.0, (departure - arrival).total_seconds() / 3600)


def _consume(hours: float, rate_mt_per_day: float) -> float:
    return max(0.0, hours) / 24 * rate_mt_per_day


def _split_rate_consumption(
    machinery: str,
    start_utc,
    end_utc,
    initial_fuel_state: MachineryFuelState,
    changeovers: list[FuelChangeoverEvent],
    rates_mt_per_day: dict[str, float],
) -> dict[str, float]:
    return _split_quantity_consumption(
        machinery,
        start_utc,
        end_utc,
        initial_fuel_state,
        changeovers,
        lambda hours, fuel=None: _consume(hours, rates_mt_per_day.get(fuel, 0.0)),
    )


def _split_quantity_consumption(
    machinery: str,
    start_utc,
    end_utc,
    initial_fuel_state: MachineryFuelState,
    changeovers: list[FuelChangeoverEvent],
    quantity_for_hours,
) -> dict[str, float]:
    totals = empty_fuel_totals()
    if end_utc <= start_utc:
        return totals
    active_fuel = initial_fuel_state.fuel_for(machinery)
    for event in sorted(changeovers, key=lambda changeover: changeover.effective_at_utc):
        if event.machinery != machinery:
            continue
        if event.effective_at_utc <= start_utc:
            active_fuel = event.to_fuel_type
    cursor = start_utc
    relevant = [
        event
        for event in sorted(changeovers, key=lambda changeover: changeover.effective_at_utc)
        if event.machinery == machinery and start_utc < event.effective_at_utc < end_utc
    ]
    for event in relevant:
        hours = (event.effective_at_utc - cursor).total_seconds() / 3600
        totals[active_fuel] += _call_quantity(quantity_for_hours, hours, active_fuel)
        active_fuel = event.to_fuel_type
        cursor = event.effective_at_utc
    hours = (end_utc - cursor).total_seconds() / 3600
    totals[active_fuel] += _call_quantity(quantity_for_hours, hours, active_fuel)
    return totals


def _call_quantity(quantity_for_hours, hours: float, fuel: str) -> float:
    try:
        return quantity_for_hours(hours, fuel)
    except TypeError:
        return quantity_for_hours(hours)


def _effective_float(override: float | None, default: float) -> float:
    return float(default if override is None else override)
