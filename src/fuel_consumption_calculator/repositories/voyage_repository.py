from __future__ import annotations

from datetime import datetime, timezone

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.voyage import GeneratorSfocPoint, RouteDefinition, SpeedConsumptionPoint, VesselEnergyConfig, VoyageLegOverride
from fuel_consumption_calculator.repositories.database import Database


class VoyageRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def list_routes(self) -> list[RouteDefinition]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT origin_port, destination_port, departure_pilot_distance_nm,
                       departure_pilotage_hours, sea_distance_nm,
                       arrival_pilot_distance_nm, arrival_pilotage_hours
                FROM route_definitions
                ORDER BY origin_port, destination_port
                """
            ).fetchall()
        return [self._row_to_route(row) for row in rows]

    def get_route(self, origin_port: str, destination_port: str) -> RouteDefinition | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT origin_port, destination_port, departure_pilot_distance_nm,
                       departure_pilotage_hours, sea_distance_nm,
                       arrival_pilot_distance_nm, arrival_pilotage_hours
                FROM route_definitions
                WHERE origin_port = ? AND destination_port = ?
                """,
                (origin_port, destination_port),
            ).fetchone()
        return self._row_to_route(row) if row else None

    def save_route(self, route: RouteDefinition) -> RouteDefinition:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO route_definitions (
                    origin_port, destination_port, departure_pilot_distance_nm,
                    departure_pilotage_hours, sea_distance_nm,
                    arrival_pilot_distance_nm, arrival_pilotage_hours,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(origin_port, destination_port)
                DO UPDATE SET
                    departure_pilot_distance_nm = excluded.departure_pilot_distance_nm,
                    departure_pilotage_hours = excluded.departure_pilotage_hours,
                    sea_distance_nm = excluded.sea_distance_nm,
                    arrival_pilot_distance_nm = excluded.arrival_pilot_distance_nm,
                    arrival_pilotage_hours = excluded.arrival_pilotage_hours,
                    updated_at = excluded.updated_at
                """,
                (
                    route.origin_port,
                    route.destination_port,
                    route.departure_pilot_distance_nm,
                    route.departure_pilotage_hours,
                    route.sea_distance_nm,
                    route.arrival_pilot_distance_nm,
                    route.arrival_pilotage_hours,
                    timestamp,
                    timestamp,
                ),
            )
        saved = self.get_route(route.origin_port, route.destination_port)
        if saved is None:
            raise RuntimeError("Route could not be read after saving.")
        return saved

    def list_overrides(self, vessel_id: int) -> list[VoyageLegOverride]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT vessel_id, sequence_number, origin_port_snapshot,
                       destination_port_snapshot, origin_departure_snapshot,
                       destination_arrival_snapshot, departure_pilot_distance_nm,
                       departure_pilotage_hours, sea_distance_nm,
                       arrival_pilot_distance_nm, arrival_pilotage_hours,
                       actual_berth_departure, actual_pilot_off,
                       actual_pilot_on, actual_berth_arrival,
                       port_reefers, departure_reefers, use_egb
                FROM voyage_leg_overrides
                WHERE vessel_id = ?
                ORDER BY sequence_number
                """,
                (vessel_id,),
            ).fetchall()
        return [self._row_to_override(row) for row in rows]

    def save_override(self, override: VoyageLegOverride) -> VoyageLegOverride:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO voyage_leg_overrides (
                    vessel_id, sequence_number, origin_port_snapshot,
                    destination_port_snapshot, origin_departure_snapshot,
                    destination_arrival_snapshot, departure_pilot_distance_nm,
                    departure_pilotage_hours, sea_distance_nm,
                    arrival_pilot_distance_nm, arrival_pilotage_hours,
                    actual_berth_departure, actual_pilot_off,
                    actual_pilot_on, actual_berth_arrival,
                    port_reefers, departure_reefers, use_egb,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    vessel_id, sequence_number, origin_port_snapshot,
                    destination_port_snapshot, origin_departure_snapshot,
                    destination_arrival_snapshot
                )
                DO UPDATE SET
                    departure_pilot_distance_nm = excluded.departure_pilot_distance_nm,
                    departure_pilotage_hours = excluded.departure_pilotage_hours,
                    sea_distance_nm = excluded.sea_distance_nm,
                    arrival_pilot_distance_nm = excluded.arrival_pilot_distance_nm,
                    arrival_pilotage_hours = excluded.arrival_pilotage_hours,
                    actual_berth_departure = excluded.actual_berth_departure,
                    actual_pilot_off = excluded.actual_pilot_off,
                    actual_pilot_on = excluded.actual_pilot_on,
                    actual_berth_arrival = excluded.actual_berth_arrival,
                    port_reefers = excluded.port_reefers,
                    departure_reefers = excluded.departure_reefers,
                    use_egb = excluded.use_egb,
                    updated_at = excluded.updated_at
                """,
                (
                    override.vessel_id,
                    override.sequence_number,
                    override.origin_port_snapshot,
                    override.destination_port_snapshot,
                    override.origin_departure_snapshot,
                    override.destination_arrival_snapshot,
                    override.departure_pilot_distance_nm,
                    override.departure_pilotage_hours,
                    override.sea_distance_nm,
                    override.arrival_pilot_distance_nm,
                    override.arrival_pilotage_hours,
                    _dt_to_text(override.actual_berth_departure),
                    _dt_to_text(override.actual_pilot_off),
                    _dt_to_text(override.actual_pilot_on),
                    _dt_to_text(override.actual_berth_arrival),
                    override.port_reefers,
                    override.departure_reefers,
                    1 if override.use_egb else 0,
                    timestamp,
                    timestamp,
                ),
            )
        for saved in self.list_overrides(override.vessel_id):
            if _same_override_identity(saved, override):
                return saved
        raise RuntimeError("Voyage override could not be read after saving.")

    def delete_override(self, override: VoyageLegOverride) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                DELETE FROM voyage_leg_overrides
                WHERE vessel_id = ?
                  AND sequence_number = ?
                  AND origin_port_snapshot = ?
                  AND destination_port_snapshot = ?
                  AND origin_departure_snapshot = ?
                  AND destination_arrival_snapshot = ?
                """,
                (
                    override.vessel_id,
                    override.sequence_number,
                    override.origin_port_snapshot,
                    override.destination_port_snapshot,
                    override.origin_departure_snapshot,
                    override.destination_arrival_snapshot,
                ),
            )

    def list_speed_points(self, vessel_id: int) -> list[SpeedConsumptionPoint]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT vessel_id, speed_knots, ulsfo_mt_per_day, vlsfo_mt_per_day, mdo_mt_per_day,
                       main_engine_load_percent
                FROM vessel_speed_consumption_points
                WHERE vessel_id = ?
                ORDER BY speed_knots
                """,
                (vessel_id,),
            ).fetchall()
        return [
            SpeedConsumptionPoint(
                vessel_id=row["vessel_id"],
                speed_knots=float(row["speed_knots"]),
                rates_mt_per_day={
                    "ULSFO": float(row["ulsfo_mt_per_day"]),
                    "VLSFO": float(row["vlsfo_mt_per_day"]),
                    "MDO": float(row["mdo_mt_per_day"]),
                },
                main_engine_load_percent=_optional_float(row["main_engine_load_percent"]),
            )
            for row in rows
        ]

    def save_speed_points(self, vessel_id: int, points: list[SpeedConsumptionPoint]) -> list[SpeedConsumptionPoint]:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._database.connect() as connection:
            connection.execute("DELETE FROM vessel_speed_consumption_points WHERE vessel_id = ?", (vessel_id,))
            for point in points:
                connection.execute(
                    """
                    INSERT INTO vessel_speed_consumption_points (
                        vessel_id, speed_knots, ulsfo_mt_per_day,
                        vlsfo_mt_per_day, mdo_mt_per_day, main_engine_load_percent,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        vessel_id,
                        point.speed_knots,
                        point.rate_for("ULSFO"),
                        point.rate_for("VLSFO"),
                        point.rate_for("MDO"),
                        point.main_engine_load_percent,
                        timestamp,
                        timestamp,
                    ),
                )
        return self.list_speed_points(vessel_id)

    def load_energy_config(self, vessel_id: int) -> VesselEnergyConfig:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT vessel_id, port_base_load_kw, sea_base_load_kw, reefer_kw_per_unit,
                       generator_rated_kw, port_running_generators, sea_running_generators,
                       aux_boiler_mt_per_hour, generator_fuel_type, boiler_fuel_type
                FROM vessel_energy_config
                WHERE vessel_id = ?
                """,
                (vessel_id,),
            ).fetchone()
        if row is None:
            return VesselEnergyConfig(vessel_id=vessel_id)
        return VesselEnergyConfig(
            vessel_id=vessel_id,
            port_base_load_kw=float(row["port_base_load_kw"]),
            sea_base_load_kw=float(row["sea_base_load_kw"]),
            reefer_kw_per_unit=float(row["reefer_kw_per_unit"]),
            generator_rated_kw=float(row["generator_rated_kw"]),
            port_running_generators=float(row["port_running_generators"]),
            sea_running_generators=float(row["sea_running_generators"]),
            aux_boiler_mt_per_hour=float(row["aux_boiler_mt_per_hour"]),
            generator_fuel_type=row["generator_fuel_type"],
            boiler_fuel_type=row["boiler_fuel_type"],
        )

    def save_energy_config(self, config: VesselEnergyConfig) -> VesselEnergyConfig:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO vessel_energy_config (
                    vessel_id, port_base_load_kw, sea_base_load_kw, reefer_kw_per_unit,
                    generator_rated_kw, port_running_generators, sea_running_generators,
                    aux_boiler_mt_per_hour, generator_fuel_type, boiler_fuel_type,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(vessel_id)
                DO UPDATE SET
                    port_base_load_kw = excluded.port_base_load_kw,
                    sea_base_load_kw = excluded.sea_base_load_kw,
                    reefer_kw_per_unit = excluded.reefer_kw_per_unit,
                    generator_rated_kw = excluded.generator_rated_kw,
                    port_running_generators = excluded.port_running_generators,
                    sea_running_generators = excluded.sea_running_generators,
                    aux_boiler_mt_per_hour = excluded.aux_boiler_mt_per_hour,
                    generator_fuel_type = excluded.generator_fuel_type,
                    boiler_fuel_type = excluded.boiler_fuel_type,
                    updated_at = excluded.updated_at
                """,
                (
                    config.vessel_id,
                    config.port_base_load_kw,
                    config.sea_base_load_kw,
                    config.reefer_kw_per_unit,
                    config.generator_rated_kw,
                    config.port_running_generators,
                    config.sea_running_generators,
                    config.aux_boiler_mt_per_hour,
                    config.generator_fuel_type,
                    config.boiler_fuel_type,
                    timestamp,
                    timestamp,
                ),
            )
        return self.load_energy_config(config.vessel_id)

    def list_generator_sfoc_points(self, vessel_id: int) -> list[GeneratorSfocPoint]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT vessel_id, load_percent, sfoc_g_per_kwh
                FROM generator_sfoc_points
                WHERE vessel_id = ?
                ORDER BY load_percent
                """,
                (vessel_id,),
            ).fetchall()
        return [
            GeneratorSfocPoint(
                vessel_id=row["vessel_id"],
                load_percent=float(row["load_percent"]),
                sfoc_g_per_kwh=float(row["sfoc_g_per_kwh"]),
            )
            for row in rows
        ]

    def save_generator_sfoc_points(self, vessel_id: int, points: list[GeneratorSfocPoint]) -> list[GeneratorSfocPoint]:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._database.connect() as connection:
            connection.execute("DELETE FROM generator_sfoc_points WHERE vessel_id = ?", (vessel_id,))
            for point in points:
                connection.execute(
                    """
                    INSERT INTO generator_sfoc_points (
                        vessel_id, load_percent, sfoc_g_per_kwh, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (vessel_id, point.load_percent, point.sfoc_g_per_kwh, timestamp, timestamp),
                )
        return self.list_generator_sfoc_points(vessel_id)

    def _row_to_route(self, row) -> RouteDefinition:
        return RouteDefinition(
            origin_port=row["origin_port"],
            destination_port=row["destination_port"],
            departure_pilot_distance_nm=float(row["departure_pilot_distance_nm"]),
            departure_pilotage_hours=float(row["departure_pilotage_hours"]),
            sea_distance_nm=float(row["sea_distance_nm"]),
            arrival_pilot_distance_nm=float(row["arrival_pilot_distance_nm"]),
            arrival_pilotage_hours=float(row["arrival_pilotage_hours"]),
        )

    def _row_to_override(self, row) -> VoyageLegOverride:
        return VoyageLegOverride(
            vessel_id=row["vessel_id"],
            sequence_number=row["sequence_number"],
            origin_port_snapshot=row["origin_port_snapshot"],
            destination_port_snapshot=row["destination_port_snapshot"],
            origin_departure_snapshot=row["origin_departure_snapshot"],
            destination_arrival_snapshot=row["destination_arrival_snapshot"],
            departure_pilot_distance_nm=_optional_float(row["departure_pilot_distance_nm"]),
            departure_pilotage_hours=_optional_float(row["departure_pilotage_hours"]),
            sea_distance_nm=_optional_float(row["sea_distance_nm"]),
            arrival_pilot_distance_nm=_optional_float(row["arrival_pilot_distance_nm"]),
            arrival_pilotage_hours=_optional_float(row["arrival_pilotage_hours"]),
            actual_berth_departure=_text_to_dt(row["actual_berth_departure"]),
            actual_pilot_off=_text_to_dt(row["actual_pilot_off"]),
            actual_pilot_on=_text_to_dt(row["actual_pilot_on"]),
            actual_berth_arrival=_text_to_dt(row["actual_berth_arrival"]),
            port_reefers=_optional_float(row["port_reefers"]),
            departure_reefers=_optional_float(row["departure_reefers"]),
            use_egb=bool(row["use_egb"]),
        )


def _same_override_identity(left: VoyageLegOverride, right: VoyageLegOverride) -> bool:
    return (
        left.vessel_id == right.vessel_id
        and left.sequence_number == right.sequence_number
        and left.origin_port_snapshot == right.origin_port_snapshot
        and left.destination_port_snapshot == right.destination_port_snapshot
        and left.origin_departure_snapshot == right.origin_departure_snapshot
        and left.destination_arrival_snapshot == right.destination_arrival_snapshot
    )


def _dt_to_text(value: datetime | None) -> str | None:
    return value.isoformat(timespec="minutes") if value else None


def _text_to_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _optional_float(value) -> float | None:
    return float(value) if value is not None else None
