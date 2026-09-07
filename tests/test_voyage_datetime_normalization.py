from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from fuel_consumption_calculator.app import build_main_window
from fuel_consumption_calculator.calculations.voyage_engine import calculate_voyage_plan
from fuel_consumption_calculator.domain.consumption import ConsumptionProfile
from fuel_consumption_calculator.domain.schedule import ScheduleCandidate
from fuel_consumption_calculator.domain.voyage import RouteDefinition, VoyageLeg, VoyageLegOverride
from fuel_consumption_calculator.paths import AppPaths
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.schedule_repository import ScheduleRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.repositories.voyage_repository import VoyageRepository
from fuel_consumption_calculator.services.voyage_service import VoyageService


UTC = timezone.utc
ROUTE = RouteDefinition("Origin", "Destination", 5.0, 2.0, 320.0, 5.0, 2.0)


def test_all_aware_utc_voyage_timestamps_are_unchanged():
    departure = datetime(2026, 1, 1, tzinfo=UTC)
    arrival = datetime(2026, 1, 2, 12, tzinfo=UTC)

    row = _calculate(_leg(departure, arrival))

    assert row.effective_berth_departure == departure
    assert row.pilot_off == datetime(2026, 1, 1, 2, tzinfo=UTC)
    assert row.pilot_on == datetime(2026, 1, 2, 10, tzinfo=UTC)
    assert row.effective_berth_arrival == arrival
    assert row.sea_hours == 32.0


def test_all_naive_legacy_voyage_timestamps_are_interpreted_as_utc():
    row = _calculate(
        _leg(
            datetime(2026, 1, 1),
            datetime(2026, 1, 2, 12),
            _override(
                actual_berth_departure=datetime(2026, 1, 1),
                actual_pilot_off=datetime(2026, 1, 1, 2),
                actual_pilot_on=datetime(2026, 1, 2, 10),
                actual_berth_arrival=datetime(2026, 1, 2, 12),
            ),
        )
    )

    assert row.sea_hours == 32.0
    assert row.effective_berth_departure == datetime(2026, 1, 1, tzinfo=UTC)
    assert row.pilot_off == datetime(2026, 1, 1, 2, tzinfo=UTC)
    assert row.pilot_on == datetime(2026, 1, 2, 10, tzinfo=UTC)
    assert row.effective_berth_arrival == datetime(2026, 1, 2, 12, tzinfo=UTC)


def test_mixed_naive_and_aware_voyage_timestamps_calculate_correct_duration():
    row = _calculate(
        _leg(
            datetime(2026, 1, 1),
            datetime(2026, 1, 2, 12, tzinfo=UTC),
            _override(actual_pilot_on=datetime(2026, 1, 2, 10, tzinfo=UTC)),
        )
    )

    assert row.pilot_off == datetime(2026, 1, 1, 2, tzinfo=UTC)
    assert row.pilot_on == datetime(2026, 1, 2, 10, tzinfo=UTC)
    assert row.sea_hours == 32.0


def test_offset_aware_and_naive_utc_timestamps_preserve_instants():
    plus_eight = timezone(timedelta(hours=8))
    row = _calculate(
        _leg(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, 12, tzinfo=UTC),
            _override(
                actual_pilot_off=datetime(2026, 1, 1, 8, tzinfo=plus_eight),
                actual_pilot_on=datetime(2026, 1, 2, 10),
            ),
        )
    )

    assert row.pilot_off == datetime(2026, 1, 1, tzinfo=UTC)
    assert row.pilot_on == datetime(2026, 1, 2, 10, tzinfo=UTC)
    assert row.sea_hours == 34.0


def test_persisted_naive_override_calculates_through_service_layer(tmp_path):
    _paths, vessel_id, events, service = _persist_legacy_override(tmp_path)
    persisted_leg = service.build_legs(vessel_id, events)[0]

    assert persisted_leg.scheduled_berth_departure.tzinfo is None
    assert persisted_leg.override is not None
    assert persisted_leg.override.actual_pilot_on is not None
    assert persisted_leg.override.actual_pilot_on.tzinfo is None

    row = service.calculate_plan(vessel_id, events, ConsumptionProfile(vessel_id, ())).legs[0]

    assert row.pilot_off == datetime(2026, 9, 1, 22, tzinfo=UTC)
    assert row.pilot_on == datetime(2026, 9, 3, 6, tzinfo=UTC)
    assert row.sea_hours == 32.0


def test_dashboard_startup_accepts_persisted_naive_voyage_override(tmp_path):
    paths, _vessel_id, _events, _service = _persist_legacy_override(tmp_path)
    app = QApplication.instance() or QApplication([])

    window = build_main_window(paths)
    try:
        assert "unavailable" not in window.dashboard_page.status_label.text().lower()
        assert window.voyage_page._timeline.stages
        assert "chronology warning" not in window.voyage_page.status_label.text().lower()
    finally:
        window.close()
        app.processEvents()


def test_mixed_timestamp_normalization_preserves_invalid_chronology_warning():
    row = _calculate(
        _leg(
            datetime(2026, 1, 2, tzinfo=UTC),
            datetime(2026, 1, 2, 12),
            _override(actual_pilot_off=datetime(2026, 1, 2, 10, tzinfo=UTC)),
        )
    )

    assert row.sea_hours == 0.0
    assert any("no available sea time" in warning for warning in row.warnings)


def _calculate(leg: VoyageLeg):
    return calculate_voyage_plan([leg], ConsumptionProfile(leg.vessel_id, ()), []).legs[0]


def _leg(
    scheduled_departure: datetime,
    scheduled_arrival: datetime,
    override: VoyageLegOverride | None = None,
) -> VoyageLeg:
    return VoyageLeg(
        vessel_id=1,
        sequence_number=2,
        origin_event_id=1,
        destination_event_id=2,
        origin_port="Origin",
        destination_port="Destination",
        scheduled_berth_departure=scheduled_departure,
        scheduled_berth_arrival=scheduled_arrival,
        route=ROUTE,
        override=override,
    )


def _override(**timestamps) -> VoyageLegOverride:
    return VoyageLegOverride(
        vessel_id=1,
        sequence_number=2,
        origin_port_snapshot="Origin",
        destination_port_snapshot="Destination",
        origin_departure_snapshot="2026-01-01T00:00",
        destination_arrival_snapshot="2026-01-02T12:00",
        **timestamps,
    )


def _candidate(
    sequence_number: int,
    port: str,
    arrival_utc: datetime,
    departure_utc: datetime | None,
) -> ScheduleCandidate:
    return ScheduleCandidate(
        sequence_number=sequence_number,
        port=port,
        event_type="Port Call",
        arrival_at=arrival_utc.replace(tzinfo=None),
        departure_at=departure_utc.replace(tzinfo=None) if departure_utc else None,
        source="test",
        source_vessel_name="Maersk Labrea",
        source_from_date=date(2026, 9, 1),
        port_timezone_id="UTC",
        arrival_at_utc=arrival_utc,
        departure_at_utc=departure_utc,
        timezone_status="RESOLVED",
    )


def _persist_legacy_override(tmp_path):
    paths = AppPaths(tmp_path / "legacy-voyage")
    paths.ensure_runtime_directories()
    database = Database(paths.database_file)
    database.initialize()
    vessel = VesselRepository(database).save_active("Maersk Labrea", "1234567")
    schedule_repository = ScheduleRepository(database)
    schedule_repository.replace_for_vessel(
        vessel.id,
        [
            _candidate(
                1,
                "Santos",
                datetime(2026, 9, 1, 8, tzinfo=UTC),
                datetime(2026, 9, 1, 20, tzinfo=UTC),
            ),
            _candidate(
                2,
                "Paranagua",
                datetime(2026, 9, 3, 8, tzinfo=UTC),
                datetime(2026, 9, 3, 20, tzinfo=UTC),
            ),
        ],
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE schedule_events SET departure_at_utc = ? WHERE vessel_id = ? AND sequence_number = 1",
            ("2026-09-01T20:00", vessel.id),
        )
    events = schedule_repository.list_for_vessel(vessel.id)
    service = VoyageService(VoyageRepository(database))
    service.save_route(RouteDefinition("Santos", "Paranagua", 5.0, 2.0, 320.0, 5.0, 2.0))
    service.save_leg_values(
        service.build_legs(vessel.id, events)[0],
        actual_pilot_on=datetime(2026, 9, 3, 6),
    )
    return paths, vessel.id, events, service
