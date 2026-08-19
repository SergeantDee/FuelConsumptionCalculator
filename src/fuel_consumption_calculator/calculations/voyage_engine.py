from __future__ import annotations

from datetime import timedelta

from fuel_consumption_calculator.calculations.consumption_engine import EventFuelConsumption, ScheduleFuelConsumption
from fuel_consumption_calculator.calculations.performance_engine import DEFAULT_ME_SFOC_POINTS, calculate_main_engine_performance, reefer_kw_per_unit
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
    main_engine_sfoc_points: list[tuple[float, float]] | None = None,
) -> VoyagePlan:
    calculated_legs: list[CalculatedVoyageLeg] = []
    warnings: list[str] = []
    ordered_points = sorted(speed_points, key=lambda point: point.speed_knots)
    ordered_sfoc_points = sorted(generator_sfoc_points or [], key=lambda point: point.load_percent)
    me_sfoc_points = main_engine_sfoc_points or list(DEFAULT_ME_SFOC_POINTS)
    detailed_me_enabled = energy_config is not None
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
        me_perf = calculate_main_engine_performance(
            required_speed,
            slip_percent=config.main_engine_slip_percent,
            speed_rpm_factor=config.speed_rpm_factor,
            power_coefficient=config.power_coefficient,
            mcr_power_kw=config.mcr_power_kw,
            sfoc_points=me_sfoc_points,
        ) if required_speed is not None and detailed_me_enabled else None
        predicted_me_load = me_perf.load_percent if me_perf else None
        leg_config = _config_for_sea(config, leg)
        sea_breakdown = _sea_consumption(
            sea_hours,
            required_speed,
            profile,
            ordered_points,
            leg_config,
            ordered_sfoc_points,
            _effective_reefers(leg.override),
            predicted_me_load,
            me_perf.fuel_mt_per_hour if me_perf else None,
            leg.override.use_egb if leg.override else False,
            leg_warnings,
            active_fuel_state,
            changeovers,
            pilot_off,
            pilot_on,
        )
        sea_consumed = sea_breakdown["total"]
        total = {
            fuel_type: _add_optional(departure_maneuvering[fuel_type], sea_consumed[fuel_type], arrival_maneuvering[fuel_type])
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
                predicted_rpm=me_perf.rpm if me_perf else None,
                predicted_me_power_kw=me_perf.power_kw if me_perf else None,
                predicted_me_sfoc_g_per_kwh=me_perf.sfoc_g_per_kwh if me_perf else None,
                predicted_me_fuel_mt_per_hour=me_perf.fuel_mt_per_hour if me_perf else None,
                hull_coefficient=config.speed_rpm_factor,
                departure_reefer_kw_per_unit=sea_breakdown["reefer_kw_per_unit"],
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
    if plan.port_breakdowns is not None:
        plan.port_breakdowns.clear()

    for event in events:
        timeline_row = timeline_by_event.get(event.id)
        if event.id in leg_consumption_by_destination:
            sea_consumed = {
                fuel_type: leg_consumption_by_destination[event.id].get(fuel_type)
                for fuel_type in FUEL_TYPES
            }
        elif event is events[0]:
            sea_consumed = {fuel_type: 0.0 for fuel_type in FUEL_TYPES}
        else:
            sea_consumed = {fuel_type: None for fuel_type in FUEL_TYPES}
        sea_hours = leg_hours_by_destination.get(event.id, timeline_row.interval_from_previous_hours if timeline_row and timeline_row.interval_from_previous_hours else 0.0)
        port_hours = _port_hours(event, actual_arrivals.get(event.id), actual_departures.get(event.id), timeline_row.port_stay_hours if timeline_row else None)
        breakdown = _port_consumption(
            event,
            port_hours,
            outgoing_leg_by_origin.get(event.id),
            profile,
            _config_for_port(plan.energy_config or VesselEnergyConfig(vessel_id=event.vessel_id), outgoing_leg_by_origin.get(event.id)),
            list(plan.generator_sfoc_points),
            plan.initial_fuel_state,
            list(plan.fuel_changeovers),
            (actual_arrivals.get(event.id) or event.effective_arrival_at),
            (actual_departures.get(event.id) or event.effective_departure_at),
        )
        if plan.port_breakdowns is not None:
            plan.port_breakdowns[event.id] = breakdown
        port_consumed = breakdown.total_consumed_mt
        consumed = {fuel_type: _add_optional(sea_consumed[fuel_type], port_consumed[fuel_type]) for fuel_type in FUEL_TYPES}
        for fuel_type in FUEL_TYPES:
            totals[fuel_type] = _add_optional(totals[fuel_type], consumed[fuel_type])
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
    detailed_me_fuel_mt_per_hour: float | None,
    requested_egb: bool,
    warnings: list[str],
    initial_fuel_state: MachineryFuelState | None = None,
    fuel_changeovers: list[FuelChangeoverEvent] | None = None,
    start_utc=None,
    end_utc=None,
) -> dict[str, float]:
    if detailed_me_fuel_mt_per_hour is not None:
        if initial_fuel_state and start_utc and end_utc:
            main_engine = _split_quantity_consumption(
                "MAIN_ENGINE",
                start_utc,
                end_utc,
                initial_fuel_state,
                fuel_changeovers or [],
                lambda hours: hours * detailed_me_fuel_mt_per_hour,
            )
        else:
            main_engine = empty_fuel_totals()
            main_engine["VLSFO"] = max(0.0, sea_hours) * detailed_me_fuel_mt_per_hour
    else:
        main_engine = {fuel_type: None for fuel_type in FUEL_TYPES}
        if sea_hours > 0:
            if speed_knots is None:
                warnings.append("Sea distance missing; main engine calculation incomplete.")
            else:
                warnings.append("ME performance/SFOC unavailable; main engine calculation incomplete.")
    generator = empty_fuel_totals()
    boiler = empty_fuel_totals()
    egb_available = predicted_me_load is not None and predicted_me_load >= 25.0
    egb_used = requested_egb and egb_available
    if requested_egb and not egb_available:
        warnings.append("EGB was selected but is unavailable below 25% predicted ME load; auxiliary boiler was used.")

    calculated_reefer_kw = reefer_kw_per_unit(config.sea_ambient_c)
    total_load_kw = config.sea_base_load_kw + departure_reefers * calculated_reefer_kw
    generator_load_percent = _generator_load_percent(total_load_kw, config.generator_rated_kw, config.sea_running_generators, warnings)
    generator_sfoc = interpolate_generator_sfoc(generator_load_percent, sfoc_points)
    detailed_ready = _energy_config_ready(config, config.sea_running_generators) and generator_load_percent is not None and generator_sfoc is not None
    missing = []
    if config.generator_rated_kw <= 0:
        missing.append("DG rated power missing")
    if config.sea_running_generators <= 0:
        missing.append("Sea DG count missing")
    if generator_load_percent is not None and generator_sfoc is None:
        missing.append("DG SFOC points missing/out of range")
    if detailed_me_fuel_mt_per_hour is None and sea_hours > 0:
        missing.append("ME performance/SFOC unavailable")
    mode = "DETAILED SFOC" if detailed_ready and detailed_me_fuel_mt_per_hour is not None else "INCOMPLETE"
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
    elif missing:
        warnings.append("Calculation incomplete: " + "; ".join(dict.fromkeys(missing)) + ".")
    total = {fuel_type: _add_optional(main_engine[fuel_type], generator[fuel_type], boiler[fuel_type]) for fuel_type in FUEL_TYPES}
    return {
        "total": total,
        "generator": generator,
        "boiler": boiler,
        "total_load_kw": total_load_kw,
        "generator_load_percent": generator_load_percent,
        "generator_sfoc": generator_sfoc,
        "mode": mode,
        "egb_used": egb_used,
        "reefer_kw_per_unit": calculated_reefer_kw,
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
    calculated_reefer_kw = reefer_kw_per_unit(config.port_ambient_c)
    total_load_kw = config.port_base_load_kw + reefers * calculated_reefer_kw
    local_warnings: list[str] = []
    generator_load_percent = _generator_load_percent(total_load_kw, config.generator_rated_kw, config.port_running_generators, local_warnings)
    generator_sfoc = interpolate_generator_sfoc(generator_load_percent, sfoc_points)
    generator = empty_fuel_totals()
    boiler = empty_fuel_totals()
    detailed_ready = _energy_config_ready(config, config.port_running_generators) and generator_load_percent is not None and generator_sfoc is not None
    if detailed_ready:
        if initial_fuel_state and start_utc and end_utc:
            generator = _split_quantity_consumption("GENERATORS", start_utc, end_utc, initial_fuel_state, fuel_changeovers or [], lambda hours: _generator_fuel(total_load_kw, generator_sfoc, hours))
            boiler = _split_quantity_consumption("AUX_BOILER", start_utc, end_utc, initial_fuel_state, fuel_changeovers or [], lambda hours: hours * config.aux_boiler_mt_per_hour)
        else:
            generator[config.generator_fuel_type] += _generator_fuel(total_load_kw, generator_sfoc, port_hours)
            boiler[config.boiler_fuel_type] += port_hours * config.aux_boiler_mt_per_hour
        mode = "DETAILED SFOC"
    else:
        mode = "INCOMPLETE"
        generator = {fuel_type: None for fuel_type in FUEL_TYPES}
        if config.generator_rated_kw <= 0:
            local_warnings.append("Calculation incomplete: DG rated power missing.")
        elif config.port_running_generators <= 0:
            local_warnings.append("Calculation incomplete: Port DG count missing.")
        elif generator_sfoc is None:
            local_warnings.append("Calculation incomplete: DG SFOC points missing/out of range.")
    total = {fuel_type: _add_optional(generator[fuel_type], boiler[fuel_type]) for fuel_type in FUEL_TYPES}
    return PortEnergyBreakdown(
        event_id=event.id,
        port=event.port,
        port_hours=port_hours,
        reefers=reefers,
        reefer_kw_per_unit=calculated_reefer_kw,
        total_electrical_load_kw=total_load_kw,
        generator_load_percent=generator_load_percent,
        generator_sfoc_g_per_kwh=generator_sfoc,
        generator_consumed_mt=generator,
        boiler_consumed_mt=boiler,
        total_consumed_mt=total,
        calculation_mode=mode,
        warnings=tuple(local_warnings),
    )


def _energy_config_ready(config: VesselEnergyConfig, running_generators: float) -> bool:
    return (
        config.generator_rated_kw > 0
        and running_generators > 0
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


def _add_optional(*values: float | None) -> float | None:
    if any(value is None for value in values):
        return None
    return sum(float(value) for value in values)


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


def _effective_reefers(override) -> float:
    if override is None:
        return 0.0
    if override.actual_departure_reefers is not None:
        return float(override.actual_departure_reefers)
    if override.departure_reefers is not None:
        return float(override.departure_reefers)
    return 0.0


def _config_for_port(config: VesselEnergyConfig, outgoing_leg: CalculatedVoyageLeg | None) -> VesselEnergyConfig:
    if outgoing_leg is None or outgoing_leg.leg.override is None or outgoing_leg.leg.override.port_ambient_c is None:
        return config
    return VesselEnergyConfig(
        vessel_id=config.vessel_id,
        port_base_load_kw=config.port_base_load_kw,
        sea_base_load_kw=config.sea_base_load_kw,
        reefer_kw_per_unit=config.reefer_kw_per_unit,
        generator_rated_kw=config.generator_rated_kw,
        port_running_generators=config.port_running_generators,
        sea_running_generators=config.sea_running_generators,
        aux_boiler_mt_per_hour=config.aux_boiler_mt_per_hour,
        generator_fuel_type=config.generator_fuel_type,
        boiler_fuel_type=config.boiler_fuel_type,
        main_engine_slip_percent=config.main_engine_slip_percent,
        speed_rpm_factor=config.speed_rpm_factor,
        power_coefficient=config.power_coefficient,
        mcr_power_kw=config.mcr_power_kw,
        port_ambient_c=float(outgoing_leg.leg.override.port_ambient_c),
        sea_ambient_c=config.sea_ambient_c,
    )


def _config_for_sea(config: VesselEnergyConfig, leg: VoyageLeg) -> VesselEnergyConfig:
    if leg.override is None or leg.override.sea_ambient_c is None:
        return config
    return VesselEnergyConfig(
        vessel_id=config.vessel_id,
        port_base_load_kw=config.port_base_load_kw,
        sea_base_load_kw=config.sea_base_load_kw,
        reefer_kw_per_unit=config.reefer_kw_per_unit,
        generator_rated_kw=config.generator_rated_kw,
        port_running_generators=config.port_running_generators,
        sea_running_generators=config.sea_running_generators,
        aux_boiler_mt_per_hour=config.aux_boiler_mt_per_hour,
        generator_fuel_type=config.generator_fuel_type,
        boiler_fuel_type=config.boiler_fuel_type,
        main_engine_slip_percent=config.main_engine_slip_percent,
        speed_rpm_factor=config.speed_rpm_factor,
        power_coefficient=config.power_coefficient,
        mcr_power_kw=config.mcr_power_kw,
        port_ambient_c=config.port_ambient_c,
        sea_ambient_c=float(leg.override.sea_ambient_c),
    )




