from __future__ import annotations

from datetime import timedelta

from fuel_consumption_calculator.calculations.consumption_engine import EventFuelConsumption, ScheduleFuelConsumption
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES, ConsumptionProfile
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.schedule_timeline import ScheduleTimeline
from fuel_consumption_calculator.domain.voyage import CalculatedVoyageLeg, SpeedConsumptionPoint, VoyageLeg, VoyagePlan, empty_fuel_totals


def calculate_voyage_plan(
    legs: list[VoyageLeg],
    profile: ConsumptionProfile,
    speed_points: list[SpeedConsumptionPoint],
) -> VoyagePlan:
    calculated_legs: list[CalculatedVoyageLeg] = []
    warnings: list[str] = []
    ordered_points = sorted(speed_points, key=lambda point: point.speed_knots)

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
        sea_consumed = _sea_consumption(sea_hours, required_speed, profile, ordered_points, leg_warnings)
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
                warnings=tuple(leg_warnings),
            )
        )

    return VoyagePlan(legs=calculated_legs, warnings=warnings)


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
        port_consumed = {
            fuel_type: _consume(port_hours, profile.rate_for("PORT", fuel_type))
            for fuel_type in FUEL_TYPES
        }
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
    points = sorted(speed_points, key=lambda point: point.speed_knots)
    if not points:
        return None
    if speed_knots < points[0].speed_knots or speed_knots > points[-1].speed_knots:
        return None
    for point in points:
        if abs(point.speed_knots - speed_knots) < 0.0001:
            return {fuel_type: point.rate_for(fuel_type) for fuel_type in FUEL_TYPES}
    for left, right in zip(points, points[1:]):
        if left.speed_knots <= speed_knots <= right.speed_knots:
            span = right.speed_knots - left.speed_knots
            ratio = (speed_knots - left.speed_knots) / span if span else 0.0
            return {
                fuel_type: left.rate_for(fuel_type) + ratio * (right.rate_for(fuel_type) - left.rate_for(fuel_type))
                for fuel_type in FUEL_TYPES
            }
    return None


def _sea_consumption(
    sea_hours: float,
    speed_knots: float | None,
    profile: ConsumptionProfile,
    speed_points: list[SpeedConsumptionPoint],
    warnings: list[str],
) -> dict[str, float]:
    interpolated = interpolate_speed_rates(speed_knots, speed_points) if speed_knots is not None else None
    if speed_knots is not None and speed_points and interpolated is None:
        warnings.append(f"Required speed {speed_knots:.2f} kn is outside configured speed-consumption points; fixed SEA rates were used.")
    rates = interpolated or {fuel_type: profile.rate_for("SEA", fuel_type) for fuel_type in FUEL_TYPES}
    return {fuel_type: _consume(sea_hours, rates[fuel_type]) for fuel_type in FUEL_TYPES}


def _port_hours(event: ScheduleEvent, actual_arrival, actual_departure, fallback: float | None) -> float:
    arrival = actual_arrival or event.arrival_at
    departure = actual_departure or event.departure_at
    if departure is None:
        return max(0.0, fallback or 0.0)
    return max(0.0, (departure - arrival).total_seconds() / 3600)


def _consume(hours: float, rate_mt_per_day: float) -> float:
    return max(0.0, hours) / 24 * rate_mt_per_day


def _effective_float(override: float | None, default: float) -> float:
    return float(default if override is None else override)
