from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from fuel_consumption_calculator.domain.schedule import ScheduleCandidate
from fuel_consumption_calculator.domain.voyage import ActualROBObservation, MachineryFuelState, RouteDefinition, VesselEnergyConfig
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.schedule_repository import ScheduleRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.repositories.voyage_repository import VoyageRepository
from fuel_consumption_calculator.services.voyage_service import VoyageService


def test_initial_machinery_fuel_state_is_unknown_until_saved(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    service = VoyageService(VoyageRepository(database))

    assert service.load_initial_fuel_state(1) is None


def test_explicitly_saved_vlsfo_machinery_fuel_state_remains_authoritative(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    vessel = VesselRepository(database).save_active("Maersk Labrea", "1234567")
    service = VoyageService(VoyageRepository(database))

    saved = service.save_initial_fuel_state(MachineryFuelState(vessel.id, "VLSFO", "VLSFO", "VLSFO"))

    assert saved == MachineryFuelState(vessel.id, "VLSFO", "VLSFO", "VLSFO")


def test_energy_config_preserves_optional_maneuvering_rates(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    vessel = VesselRepository(database).save_active("Maersk Labrea", "1234567")
    service = VoyageService(VoyageRepository(database))

    saved = service.save_energy_config(
        VesselEnergyConfig(
            vessel.id,
            maneuvering_main_engine_mt_per_hour=0.0,
            maneuvering_generators_mt_per_hour=None,
            maneuvering_aux_boiler_mt_per_hour=0.1,
        )
    )

    assert saved.maneuvering_main_engine_mt_per_hour == 0.0
    assert saved.maneuvering_generators_mt_per_hour is None
    assert saved.maneuvering_aux_boiler_mt_per_hour == 0.1


def test_route_library_saves_and_loads_operational_distances(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    service = VoyageService(VoyageRepository(database))

    saved = service.save_route(RouteDefinition("Santos", "Rotterdam", 2.0, 1.5, 5_100.0, 3.0, 1.0))

    assert saved in service.list_routes()


def test_actual_rob_observation_requires_complete_fuel_snapshot(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    vessel = VesselRepository(database).save_active("Maersk Labrea", "1234567")
    service = VoyageService(VoyageRepository(database))

    observation = ActualROBObservation(
        id=None,
        vessel_id=vessel.id,
        effective_at_utc=datetime(2026, 9, 1, 12, tzinfo=timezone.utc),
        quantities_mt={"ULSFO": 100.0, "VLSFO": 50.0},
    )

    with pytest.raises(ValueError, match="complete"):
        service.save_actual_rob_observation(observation)

def _candidate(
    sequence: int,
    port: str,
    arrival: datetime,
    departure: datetime | None,
) -> ScheduleCandidate:
    return ScheduleCandidate(
        sequence_number=sequence,
        port=port,
        event_type="Port Call",
        arrival_at=arrival.replace(tzinfo=None),
        departure_at=departure.replace(tzinfo=None) if departure else None,
        source="test",
        source_vessel_name="Maersk Labrea",
        source_from_date=date(2026, 9, 1),
        port_timezone_id="UTC",
        arrival_at_utc=arrival,
        departure_at_utc=departure,
        timezone_status="RESOLVED",
    )


def test_voyage_override_survives_schedule_eta_etd_refresh(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()

    vessel = VesselRepository(database).save_active("Maersk Labrea", "1234567")
    schedule_repository = ScheduleRepository(database)
    voyage_service = VoyageService(VoyageRepository(database))

    original_events = schedule_repository.replace_for_vessel(
        vessel.id,
        [
            _candidate(
                1,
                "Santos",
                datetime(2026, 9, 1, 8, tzinfo=timezone.utc),
                datetime(2026, 9, 1, 20, tzinfo=timezone.utc),
            ),
            _candidate(
                2,
                "Paranagua",
                datetime(2026, 9, 3, 8, tzinfo=timezone.utc),
                datetime(2026, 9, 3, 20, tzinfo=timezone.utc),
            ),
        ],
    )

    original_leg = voyage_service.build_legs(vessel.id, original_events)[0]

    voyage_service.save_leg_values(
        original_leg,
        actual_berth_departure=datetime(2026, 9, 1, 21, tzinfo=timezone.utc),
        actual_pilot_off=datetime(2026, 9, 1, 22, tzinfo=timezone.utc),
        departure_reefers=250,
        sea_ambient_c=32,
        use_egb=True,
    )

    refreshed_events = schedule_repository.replace_for_vessel(
        vessel.id,
        [
            _candidate(
                1,
                "Santos",
                datetime(2026, 9, 1, 9, tzinfo=timezone.utc),
                datetime(2026, 9, 1, 23, tzinfo=timezone.utc),
            ),
            _candidate(
                2,
                "Paranagua",
                datetime(2026, 9, 3, 12, tzinfo=timezone.utc),
                datetime(2026, 9, 4, 0, tzinfo=timezone.utc),
            ),
        ],
    )

    refreshed_leg = voyage_service.build_legs(vessel.id, refreshed_events)[0]

    assert refreshed_leg.override is not None
    assert refreshed_leg.override.actual_berth_departure == datetime(
        2026, 9, 1, 21, tzinfo=timezone.utc
    )
    assert refreshed_leg.override.actual_pilot_off == datetime(
        2026, 9, 1, 22, tzinfo=timezone.utc
    )
    assert refreshed_leg.override.departure_reefers == 250
    assert refreshed_leg.override.sea_ambient_c == 32
    assert refreshed_leg.override.use_egb is True

    assert refreshed_leg.scheduled_berth_departure == datetime(
        2026, 9, 1, 23, tzinfo=timezone.utc
    )
    assert refreshed_leg.scheduled_berth_arrival == datetime(
        2026, 9, 3, 12, tzinfo=timezone.utc
    )

def test_voyage_override_is_not_auto_matched_when_port_pair_is_ambiguous(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()

    vessel = VesselRepository(database).save_active("Maersk Labrea", "1234567")
    schedule_repository = ScheduleRepository(database)
    voyage_service = VoyageService(VoyageRepository(database))

    original_events = schedule_repository.replace_for_vessel(
        vessel.id,
        [
            _candidate(
                1,
                "Santos",
                datetime(2026, 9, 1, 8, tzinfo=timezone.utc),
                datetime(2026, 9, 1, 20, tzinfo=timezone.utc),
            ),
            _candidate(
                2,
                "Paranagua",
                datetime(2026, 9, 3, 8, tzinfo=timezone.utc),
                datetime(2026, 9, 3, 20, tzinfo=timezone.utc),
            ),
            _candidate(
                3,
                "Santos",
                datetime(2026, 9, 5, 8, tzinfo=timezone.utc),
                datetime(2026, 9, 5, 20, tzinfo=timezone.utc),
            ),
            _candidate(
                4,
                "Paranagua",
                datetime(2026, 9, 7, 8, tzinfo=timezone.utc),
                datetime(2026, 9, 7, 20, tzinfo=timezone.utc),
            ),
        ],
    )

    first_leg = voyage_service.build_legs(vessel.id, original_events)[0]

    voyage_service.save_leg_values(
        first_leg,
        actual_pilot_off=datetime(2026, 9, 1, 22, tzinfo=timezone.utc),
    )

    refreshed_events = schedule_repository.replace_for_vessel(
        vessel.id,
        [
            _candidate(
                1,
                "Santos",
                datetime(2026, 9, 1, 9, tzinfo=timezone.utc),
                datetime(2026, 9, 1, 23, tzinfo=timezone.utc),
            ),
            _candidate(
                2,
                "Paranagua",
                datetime(2026, 9, 3, 12, tzinfo=timezone.utc),
                datetime(2026, 9, 3, 23, tzinfo=timezone.utc),
            ),
            _candidate(
                3,
                "Santos",
                datetime(2026, 9, 5, 10, tzinfo=timezone.utc),
                datetime(2026, 9, 5, 22, tzinfo=timezone.utc),
            ),
            _candidate(
                4,
                "Paranagua",
                datetime(2026, 9, 7, 11, tzinfo=timezone.utc),
                datetime(2026, 9, 7, 23, tzinfo=timezone.utc),
            ),
        ],
    )

    refreshed_legs = voyage_service.build_legs(vessel.id, refreshed_events)
    santos_paranagua_legs = [
        leg
        for leg in refreshed_legs
        if leg.origin_port == "Santos" and leg.destination_port == "Paranagua"
    ]

    assert len(santos_paranagua_legs) == 2
    assert all(leg.override is None for leg in santos_paranagua_legs)
