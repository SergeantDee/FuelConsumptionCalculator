from __future__ import annotations

from datetime import datetime

from fuel_consumption_calculator.calculations.consumption_engine import ScheduleFuelConsumption
from fuel_consumption_calculator.calculations.voyage_engine import calculate_consumption_with_voyage, calculate_voyage_plan
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES, ConsumptionProfile
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.schedule_timeline import ScheduleTimeline
from fuel_consumption_calculator.domain.voyage import RouteDefinition, SpeedConsumptionPoint, VoyageLeg, VoyageLegOverride, VoyagePlan
from fuel_consumption_calculator.legacy_voyage_data import legacy_pilot_info, legacy_sea_distance
from fuel_consumption_calculator.repositories.voyage_repository import VoyageRepository


class VoyageService:
    def __init__(self, repository: VoyageRepository) -> None:
        self._repository = repository

    def list_routes(self) -> list[RouteDefinition]:
        return self._repository.list_routes()

    def save_route(self, route: RouteDefinition) -> RouteDefinition:
        self._validate_route(route)
        return self._repository.save_route(route)

    def list_speed_points(self, vessel_id: int) -> list[SpeedConsumptionPoint]:
        return self._repository.list_speed_points(vessel_id)

    def save_speed_points(self, vessel_id: int, points: list[SpeedConsumptionPoint]) -> list[SpeedConsumptionPoint]:
        self._validate_speed_points(points)
        return self._repository.save_speed_points(vessel_id, points)

    def build_speed_point(self, vessel_id: int, speed_knots: float, rates: dict[str, float]) -> SpeedConsumptionPoint:
        point = SpeedConsumptionPoint(
            vessel_id=vessel_id,
            speed_knots=float(speed_knots),
            rates_mt_per_day={fuel_type: float(rates.get(fuel_type, 0.0)) for fuel_type in FUEL_TYPES},
        )
        self._validate_speed_points([point])
        return point

    def build_legs(self, vessel_id: int, events: list[ScheduleEvent]) -> list[VoyageLeg]:
        ordered_events = sorted(events, key=lambda event: (event.sequence_number, event.arrival_at, event.id))
        overrides = self._matching_overrides(vessel_id, ordered_events)
        legs: list[VoyageLeg] = []
        for origin, destination in zip(ordered_events, ordered_events[1:]):
            if origin.departure_at is None:
                continue
            identity = _identity_for_leg(vessel_id, origin, destination)
            route = self._repository.get_route(origin.port, destination.port)
            status = "OK"
            message = ""
            if route is None:
                route = self._legacy_route(origin.port, destination.port)
                if route.sea_distance_nm > 0:
                    self._repository.save_route(route)
                    message = "Imported from legacy distance defaults."
                else:
                    status = "MISSING_ROUTE"
                    message = "Route distance is missing; enter and save route values."
            legs.append(
                VoyageLeg(
                    vessel_id=vessel_id,
                    sequence_number=destination.sequence_number,
                    origin_event_id=origin.id,
                    destination_event_id=destination.id,
                    origin_port=origin.port,
                    destination_port=destination.port,
                    scheduled_berth_departure=origin.departure_at,
                    scheduled_berth_arrival=destination.arrival_at,
                    route=route,
                    override=overrides.get(identity),
                    status=status,
                    message=message,
                )
            )
        return legs

    def calculate_plan(
        self,
        vessel_id: int,
        events: list[ScheduleEvent],
        profile: ConsumptionProfile,
    ) -> VoyagePlan:
        return calculate_voyage_plan(
            self.build_legs(vessel_id, events),
            profile,
            self.list_speed_points(vessel_id),
        )

    def calculate_schedule_consumption(
        self,
        vessel_id: int,
        events: list[ScheduleEvent],
        timeline: ScheduleTimeline,
        profile: ConsumptionProfile,
    ) -> ScheduleFuelConsumption:
        plan = self.calculate_plan(vessel_id, events, profile)
        return calculate_consumption_with_voyage(timeline, events, plan, profile)

    def save_leg_values(
        self,
        leg: VoyageLeg,
        *,
        departure_pilot_distance_nm: float | None = None,
        departure_pilotage_hours: float | None = None,
        sea_distance_nm: float | None = None,
        arrival_pilot_distance_nm: float | None = None,
        arrival_pilotage_hours: float | None = None,
        actual_berth_departure: datetime | None = None,
        actual_pilot_off: datetime | None = None,
        actual_pilot_on: datetime | None = None,
        actual_berth_arrival: datetime | None = None,
        save_library: bool = False,
    ) -> VoyageLegOverride:
        if save_library:
            self.save_route(
                RouteDefinition(
                    origin_port=leg.origin_port,
                    destination_port=leg.destination_port,
                    departure_pilot_distance_nm=_fallback(departure_pilot_distance_nm, leg.route.departure_pilot_distance_nm),
                    departure_pilotage_hours=_fallback(departure_pilotage_hours, leg.route.departure_pilotage_hours),
                    sea_distance_nm=_fallback(sea_distance_nm, leg.route.sea_distance_nm),
                    arrival_pilot_distance_nm=_fallback(arrival_pilot_distance_nm, leg.route.arrival_pilot_distance_nm),
                    arrival_pilotage_hours=_fallback(arrival_pilotage_hours, leg.route.arrival_pilotage_hours),
                )
            )
        override = VoyageLegOverride(
            vessel_id=leg.vessel_id,
            sequence_number=leg.sequence_number,
            origin_port_snapshot=leg.origin_port,
            destination_port_snapshot=leg.destination_port,
            origin_departure_snapshot=leg.scheduled_berth_departure.isoformat(timespec="minutes"),
            destination_arrival_snapshot=leg.scheduled_berth_arrival.isoformat(timespec="minutes"),
            departure_pilot_distance_nm=departure_pilot_distance_nm,
            departure_pilotage_hours=departure_pilotage_hours,
            sea_distance_nm=sea_distance_nm,
            arrival_pilot_distance_nm=arrival_pilot_distance_nm,
            arrival_pilotage_hours=arrival_pilotage_hours,
            actual_berth_departure=actual_berth_departure,
            actual_pilot_off=actual_pilot_off,
            actual_pilot_on=actual_pilot_on,
            actual_berth_arrival=actual_berth_arrival,
        )
        self._validate_override(override)
        return self._repository.save_override(override)

    def reset_leg_to_library(self, leg: VoyageLeg) -> None:
        if leg.override is not None:
            self._repository.delete_override(leg.override)

    def distance_coverage(self, vessel_id: int, events: list[ScheduleEvent]) -> tuple[int, int, int]:
        legs = self.build_legs(vessel_id, events)
        total = len(legs)
        matched = sum(1 for leg in legs if leg.route.sea_distance_nm > 0)
        return total, matched, total - matched

    def _matching_overrides(self, vessel_id: int, events: list[ScheduleEvent]) -> dict[tuple, VoyageLegOverride]:
        current_identities = {
            _identity_for_leg(vessel_id, origin, destination)
            for origin, destination in zip(events, events[1:])
            if origin.departure_at is not None
        }
        return {
            _override_identity(override): override
            for override in self._repository.list_overrides(vessel_id)
            if _override_identity(override) in current_identities
        }

    def _legacy_route(self, origin_port: str, destination_port: str) -> RouteDefinition:
        origin_pilot_dist, _origin_in, origin_out = legacy_pilot_info(origin_port)
        dest_pilot_dist, dest_in, _dest_out = legacy_pilot_info(destination_port)
        return RouteDefinition(
            origin_port=origin_port,
            destination_port=destination_port,
            departure_pilot_distance_nm=origin_pilot_dist,
            departure_pilotage_hours=origin_out,
            sea_distance_nm=legacy_sea_distance(origin_port, destination_port) or 0.0,
            arrival_pilot_distance_nm=dest_pilot_dist,
            arrival_pilotage_hours=dest_in,
        )

    def _validate_route(self, route: RouteDefinition) -> None:
        if not route.origin_port.strip() or not route.destination_port.strip():
            raise ValueError("Origin and destination ports are required.")
        for value in (
            route.departure_pilot_distance_nm,
            route.departure_pilotage_hours,
            route.sea_distance_nm,
            route.arrival_pilot_distance_nm,
            route.arrival_pilotage_hours,
        ):
            if value < 0:
                raise ValueError("Route distances and durations cannot be negative.")

    def _validate_override(self, override: VoyageLegOverride) -> None:
        for value in (
            override.departure_pilot_distance_nm,
            override.departure_pilotage_hours,
            override.sea_distance_nm,
            override.arrival_pilot_distance_nm,
            override.arrival_pilotage_hours,
        ):
            if value is not None and value < 0:
                raise ValueError("Voyage override distances and durations cannot be negative.")

    def _validate_speed_points(self, points: list[SpeedConsumptionPoint]) -> None:
        seen = set()
        for point in points:
            if point.speed_knots <= 0:
                raise ValueError("Speed points must be greater than zero.")
            if point.speed_knots in seen:
                raise ValueError("Duplicate speed point.")
            seen.add(point.speed_knots)
            for fuel_type in FUEL_TYPES:
                if point.rate_for(fuel_type) < 0:
                    raise ValueError("Speed consumption rates cannot be negative.")


def _identity_for_leg(vessel_id: int, origin: ScheduleEvent, destination: ScheduleEvent) -> tuple:
    return (
        vessel_id,
        destination.sequence_number,
        origin.port,
        destination.port,
        origin.departure_at.isoformat(timespec="minutes") if origin.departure_at else None,
        destination.arrival_at.isoformat(timespec="minutes"),
    )


def _override_identity(override: VoyageLegOverride) -> tuple:
    return (
        override.vessel_id,
        override.sequence_number,
        override.origin_port_snapshot,
        override.destination_port_snapshot,
        override.origin_departure_snapshot,
        override.destination_arrival_snapshot,
    )


def _fallback(value: float | None, default: float) -> float:
    return float(default if value is None else value)
