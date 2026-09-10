from __future__ import annotations

import os
from dataclasses import replace
from datetime import date, datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox
import pytest

from fuel_consumption_calculator.app import build_main_window
from fuel_consumption_calculator.domain.fuel_tank import FuelTank
from fuel_consumption_calculator.domain.schedule import ScheduleCandidate
from fuel_consumption_calculator.domain.voyage import GeneratorSfocPoint, MachineryFuelState, VesselEnergyConfig
from fuel_consumption_calculator.paths import AppPaths
from fuel_consumption_calculator.repositories.consumption_repository import ConsumptionRepository
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.repositories.rob_repository import ROBRepository
from fuel_consumption_calculator.repositories.schedule_repository import ScheduleRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.repositories.voyage_repository import VoyageRepository
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService
from fuel_consumption_calculator.services.planning_readiness_service import (
    AGGREGATE_ROB_AVAILABLE,
    INITIAL_FUEL_STATE_CONFIGURED,
    PERFORMANCE_CONFIGURED,
    SCHEDULE_AVAILABLE,
    TANK_CONFIGURATION_AVAILABLE,
    TANK_PHYSICAL_ROB_AVAILABLE,
    VESSEL_CONFIGURED,
    VOYAGE_PROJECTION_AVAILABLE,
    PlanningReadiness,
    PlanningReadinessService,
    ReadinessCheck,
)
from fuel_consumption_calculator.services.rob_service import ROBService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.settings_service import SettingsService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.services.voyage_service import VoyageService
from fuel_consumption_calculator.ui.setup_wizard import SetupWizard
from fuel_consumption_calculator.ui.widgets.vessel_clock import vessel_local_time


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _services(tmp_path):
    database = Database(tmp_path / "planning.db")
    database.initialize()
    vessel = VesselService(VesselRepository(database))
    schedule = ScheduleService(ScheduleRepository(database))
    voyage = VoyageService(VoyageRepository(database))
    consumption = ConsumptionService(ConsumptionRepository(database), voyage)
    rob = ROBService(ROBRepository(database))
    tanks = FuelTankService(FuelTankRepository(database))
    settings = SettingsService(tmp_path / "settings.json")
    readiness = PlanningReadinessService(vessel, schedule, consumption, voyage, rob, tanks)
    return database, vessel, schedule, voyage, consumption, rob, tanks, settings, readiness


def _configured_vessel(services):
    return services[1].configure_active_vessel("MV Existing", "1234567")


def _wizard(services):
    _, vessel, schedule, voyage, consumption, rob, tanks, settings, readiness = services
    return SetupWizard(vessel, schedule, consumption, voyage, rob, tanks, settings, readiness)


def test_fresh_database_requires_initialization_and_missing_rob_is_unknown(tmp_path):
    services = _services(tmp_path)
    readiness = services[-1].evaluate()

    assert not readiness.is_available(VESSEL_CONFIGURED)
    vessel = _configured_vessel(services)
    assert not services[5].has_starting_rob(vessel.id)
    assert services[5].load_starting_rob(vessel.id).quantity_for("VLSFO") is None


def test_wizard_preloads_existing_vessel_and_preserves_it(tmp_path, qapp):
    services = _services(tmp_path)
    vessel = _configured_vessel(services)

    wizard = _wizard(services)

    assert wizard.vessel_name_input.text() == vessel.name
    assert wizard.imo_input.text() == vessel.imo
    assert services[1].get_active_vessel() == vessel
    assert services[7].initialization_wizard_seen()


@pytest.mark.parametrize(
    ("minutes", "display"),
    ((60, "GMT +01:00"), (-210, "GMT -03:30")),
)
def test_wizard_preselects_saved_vessel_gmt_offset(tmp_path, qapp, minutes, display):
    services = _services(tmp_path)
    _configured_vessel(services)
    services[7].save_vessel_time_offset_minutes(minutes)

    wizard = _wizard(services)

    assert wizard.timezone_input.currentData() == minutes
    assert wizard.timezone_input.currentText() == display
    assert "minutes from UTC" not in wizard.timezone_input.currentText()


@pytest.mark.parametrize("minutes", (120, 330, 345))
def test_wizard_gmt_selection_persists_internal_offset_minutes(tmp_path, qapp, minutes):
    services = _services(tmp_path)
    _configured_vessel(services)
    wizard = _wizard(services)
    wizard.timezone_input.setCurrentIndex(wizard.timezone_input.findData(minutes))

    assert wizard._save_step(0)
    assert services[7].vessel_time_offset_minutes() == minutes


def test_vessel_local_preview_updates_immediately_without_changing_utc_semantics(tmp_path, qapp):
    services = _services(tmp_path)
    _configured_vessel(services)
    wizard = _wizard(services)
    wizard.timezone_input.setCurrentIndex(wizard.timezone_input.findData(-720))
    first_preview = wizard.time_preview.text()
    wizard.timezone_input.setCurrentIndex(wizard.timezone_input.findData(840))

    assert wizard.time_preview.text() != first_preview
    assert "Vessel Local:" in wizard.time_preview.text()
    assert "UTC:" in wizard.time_preview.text()
    utc_instant = datetime(2026, 9, 9, 2, 15, tzinfo=timezone.utc)
    assert vessel_local_time(utc_instant, 120) == datetime(2026, 9, 9, 4, 15, tzinfo=timezone.utc)
    assert utc_instant == datetime(2026, 9, 9, 2, 15, tzinfo=timezone.utc)


def test_safe_defaults_only_load_existing_technical_defaults_and_never_rob(tmp_path, qapp):
    services = _services(tmp_path)
    vessel = _configured_vessel(services)
    wizard = _wizard(services)

    wizard._use_performance_defaults()

    defaults = VesselEnergyConfig(vessel.id)
    assert wizard._energy_inputs["mcr_power_kw"].value() == pytest.approx(defaults.mcr_power_kw)
    assert wizard._energy_inputs["generator_rated_kw"].value() == 0
    assert not services[5].has_starting_rob(vessel.id)


def test_defaults_merge_known_values_and_preserve_fields_without_defaults(tmp_path, qapp, monkeypatch):
    services = _services(tmp_path)
    vessel = _configured_vessel(services)
    voyage = services[3]
    configured = replace(
        VesselEnergyConfig(vessel.id),
        mcr_power_kw=41000,
        generator_rated_kw=5000,
        port_running_generators=2,
        sea_running_generators=1,
        port_base_load_kw=1500,
        sea_base_load_kw=1000,
        reefer_kw_per_unit=3,
        aux_boiler_mt_per_hour=0.10,
        maneuvering_main_engine_mt_per_hour=0.25,
        maneuvering_generators_mt_per_hour=0.05,
        maneuvering_aux_boiler_mt_per_hour=0.02,
    )
    voyage.save_energy_config(configured)
    voyage.save_generator_sfoc_points(vessel.id, [GeneratorSfocPoint(vessel.id, 50, 200)])
    rob = services[5]
    original_rob = rob.save_starting_rob(
        rob.build_starting_rob(vessel.id, {"ULSFO": 1, "VLSFO": 200, "MDO": 30})
    )
    wizard = _wizard(services)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    wizard._use_performance_defaults()

    assert wizard._energy_inputs["mcr_power_kw"].value() == VesselEnergyConfig(vessel.id).mcr_power_kw
    assert wizard._energy_inputs["generator_rated_kw"].value() == 5000
    assert wizard._energy_inputs["port_base_load_kw"].value() == 1500
    assert wizard._energy_inputs["aux_boiler_mt_per_hour"].value() == pytest.approx(0.10)
    assert wizard._maneuvering_inputs["maneuvering_main_engine_mt_per_hour"].text() == "0.25"
    assert wizard.dg_curve_input.text() == "50:200"
    assert wizard.profile_type_label.text() == "DEFAULTS + USER VALUES"
    assert rob.load_starting_rob(vessel.id) == original_rob


def test_defaults_leave_undefined_required_values_visibly_unconfigured(tmp_path, qapp):
    services = _services(tmp_path)
    _configured_vessel(services)
    wizard = _wizard(services)

    wizard._use_performance_defaults()

    assert wizard._energy_inputs["generator_rated_kw"].text() == "Unconfigured"
    assert wizard._energy_inputs["port_base_load_kw"].text() == "Unconfigured"
    assert wizard._energy_inputs["aux_boiler_mt_per_hour"].text() == "Unconfigured"
    assert wizard.dg_curve_input.text() == ""
    performance = services[-1].evaluate().check("PERFORMANCE_CONFIGURED")
    assert not performance.available
    assert "DG rated power" in performance.missing_inputs


def test_canceling_defaults_confirmation_preserves_all_displayed_user_values(tmp_path, qapp, monkeypatch):
    services = _services(tmp_path)
    vessel = _configured_vessel(services)
    services[3].save_energy_config(replace(VesselEnergyConfig(vessel.id), mcr_power_kw=41000, generator_rated_kw=5000))
    wizard = _wizard(services)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)

    wizard._use_performance_defaults()

    assert wizard._energy_inputs["mcr_power_kw"].value() == 41000
    assert wizard._energy_inputs["generator_rated_kw"].value() == 5000
    assert wizard.profile_type_label.text() == "USER CONFIGURED"


def test_missing_and_configured_initial_fuel_state_update_readiness(tmp_path):
    services = _services(tmp_path)
    vessel = _configured_vessel(services)
    readiness = services[-1]

    assert not readiness.evaluate().is_available(INITIAL_FUEL_STATE_CONFIGURED)
    services[3].save_initial_fuel_state(MachineryFuelState(vessel.id, "VLSFO", "ULSFO", "MDO"))
    assert readiness.evaluate().is_available(INITIAL_FUEL_STATE_CONFIGURED)


def test_missing_schedule_is_actionable(tmp_path):
    services = _services(tmp_path)
    _configured_vessel(services)

    readiness = services[-1].evaluate()

    assert not readiness.is_available(SCHEDULE_AVAILABLE)
    assert "schedule" in readiness.blocking_reason.lower()


def test_tank_physical_rob_does_not_control_aggregate_rob_readiness(tmp_path):
    services = _services(tmp_path)
    vessel = _configured_vessel(services)
    rob, tanks = services[5], services[6]
    rob.save_starting_rob(rob.build_starting_rob(vessel.id, {"ULSFO": 10, "VLSFO": 20, "MDO": 5}))
    tanks.create_tank(FuelTank(None, vessel.id, "TEST TANK", "BUNKER", 100, "SOUNDING"))

    readiness = services[-1].evaluate()

    assert readiness.is_available(AGGREGATE_ROB_AVAILABLE)
    assert not readiness.is_available(TANK_PHYSICAL_ROB_AVAILABLE)


def test_physical_tank_rob_readiness_reports_unavailable_partial_and_complete(tmp_path):
    services = _services(tmp_path)
    vessel = _configured_vessel(services)
    tanks = services[6]
    first = tanks.create_tank(FuelTank(None, vessel.id, "Bunker 1", "BUNKER", 100, "SOUNDING"))
    second = tanks.create_tank(FuelTank(None, vessel.id, "Bunker 2", "BUNKER", 100, "SOUNDING"))

    unavailable = services[-1].evaluate().check(TANK_PHYSICAL_ROB_AVAILABLE)
    assert unavailable.status == "UNAVAILABLE"
    assert "no physical tank mass recorded" in unavailable.label

    tanks.save_manual_tank_rob(tank_id=first.id, fuel_type="VLSFO", mass_mt=10)
    partial = services[-1].evaluate().check(TANK_PHYSICAL_ROB_AVAILABLE)
    assert partial.status == "PARTIAL"
    assert "1 of 2 applicable tanks known" in partial.label

    tanks.save_manual_tank_rob(tank_id=second.id, fuel_type="VLSFO", mass_mt=0)
    complete = services[-1].evaluate().check(TANK_PHYSICAL_ROB_AVAILABLE)
    assert complete.status == "COMPLETE"
    assert complete.available
    assert "2 of 2 applicable tanks known" in complete.label


def test_wizard_inline_status_omits_missing_optional_reason(tmp_path, qapp):
    services = _services(tmp_path)
    vessel = _configured_vessel(services)
    services[6].create_tank(FuelTank(None, vessel.id, "Bunker 1", "BUNKER", 100, "SOUNDING"))

    wizard = _wizard(services)

    assert "Tank physical ROB unavailable" in wizard.tank_rob_status.text()
    assert "None" not in wizard.tank_rob_status.text()


def test_wizard_unavailable_states_do_not_use_affirmative_labels(tmp_path, qapp):
    services = _services(tmp_path)
    _configured_vessel(services)
    wizard = _wizard(services)

    wizard._refresh_readiness()
    labels = {key: label.text() for key, label in wizard.readiness_labels.items()}

    assert wizard.schedule_status.text().startswith("⚠ Schedule unavailable")
    assert labels[SCHEDULE_AVAILABLE].startswith("✕ Schedule unavailable")
    assert labels[VOYAGE_PROJECTION_AVAILABLE].startswith("✕ Voyage projection unavailable")
    assert labels[PERFORMANCE_CONFIGURED].startswith("✕ Performance model not configured")
    assert not any(text.startswith(("✕ Schedule available", "✕ Voyage projection available")) for text in labels.values())


def test_bunker_readiness_status_uses_label_when_optional_reason_is_absent(tmp_path, qapp):
    paths = AppPaths(tmp_path)
    window = build_main_window(paths)
    vessel, _schedule, _consumption, _voyage, rob, tanks, _settings, _readiness = window._setup_services
    configured = vessel.configure_active_vessel("MV Status", "1234567")
    rob.save_starting_rob(rob.build_starting_rob(configured.id, {"ULSFO": 10, "VLSFO": 20, "MDO": 5}))
    tanks.create_tank(FuelTank(None, configured.id, "Bunker 1", "BUNKER", 100, "SOUNDING"))

    window.bunker_page.refresh()

    assert "Tank physical ROB unavailable" in window.bunker_page.status_label.text()
    assert "None" not in window.bunker_page.status_label.text()
    window.close()


def test_optional_tank_rob_and_future_projection_warning_do_not_make_setup_incomplete():
    checks = (
        ReadinessCheck(VESSEL_CONFIGURED, True, True, "Vessel configured"),
        ReadinessCheck(PERFORMANCE_CONFIGURED, True, True, "Performance configured"),
        ReadinessCheck(INITIAL_FUEL_STATE_CONFIGURED, True, True, "Fuel configured"),
        ReadinessCheck(AGGREGATE_ROB_AVAILABLE, True, True, "ROB configured"),
        ReadinessCheck(TANK_CONFIGURATION_AVAILABLE, True, False, "Tanks configured"),
        ReadinessCheck(
            TANK_PHYSICAL_ROB_AVAILABLE,
            False,
            False,
            "Tank physical ROB unavailable",
            status="UNAVAILABLE",
        ),
        ReadinessCheck(SCHEDULE_AVAILABLE, True, True, "Schedule configured"),
        ReadinessCheck(VOYAGE_PROJECTION_AVAILABLE, False, True, "Projection unavailable"),
    )
    readiness = PlanningReadiness(checks, blocking_reason="Future sea distance missing")

    assert readiness.setup_complete
    assert not readiness.ready


def test_wizard_blank_creates_no_observation_and_explicit_zero(tmp_path, qapp):
    services = _services(tmp_path)
    vessel = _configured_vessel(services)
    tanks = services[6]
    unknown = tanks.create_tank(FuelTank(None, vessel.id, "Bunker 1", "BUNKER", 100, "SOUNDING"))
    empty = tanks.create_tank(FuelTank(None, vessel.id, "Bunker 2", "BUNKER", 100, "SOUNDING"))
    wizard = _wizard(services)
    unknown_fuel, unknown_mass = wizard._tank_rob_rows[unknown.id]
    empty_fuel, empty_mass = wizard._tank_rob_rows[empty.id]
    unknown_fuel.setCurrentText("VLSFO")
    unknown_mass.clear()
    empty_fuel.setCurrentText("MDO")
    empty_mass.setText("0.00")

    assert wizard._save_step(5)
    assert tanks.list_manual_tank_rob_history(unknown.id) == []
    assert tanks.get_latest_physical_mass_anchor(empty.id).mass_mt == 0.0
    assert "Known tanks: 1 / 2" in wizard.tank_rob_summary.text()


def test_first_unresolved_voyage_stage_is_identified(tmp_path):
    services = _services(tmp_path)
    vessel = _configured_vessel(services)
    schedule = services[2]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)
    schedule.confirm_schedule_update(vessel.id, [
        ScheduleCandidate(1, "Rotterdam", "PORT", start, start.replace(hour=12), "MANUAL", vessel.name, date(2026, 1, 1), port_timezone_id="UTC", arrival_at_utc=start, departure_at_utc=start.replace(hour=12)),
        ScheduleCandidate(2, "Hamburg", "PORT", end, end.replace(hour=12), "MANUAL", vessel.name, date(2026, 1, 1), port_timezone_id="UTC", arrival_at_utc=end, departure_at_utc=end.replace(hour=12)),
    ])

    readiness = services[-1].evaluate()

    assert readiness.first_blocking_stage == "Rotterdam PORT STAY"
    assert "DG rated power" in readiness.blocking_reason
    assert not readiness.is_available(VOYAGE_PROJECTION_AVAILABLE)


def test_wizard_completion_flag_never_overrides_dynamic_readiness(tmp_path):
    services = _services(tmp_path)
    services[7].save_initialization_wizard_state(seen=True, completed=True)

    assert services[7].initialization_wizard_completed()
    assert not services[-1].evaluate().ready


def test_rerunning_wizard_preserves_user_values(tmp_path, qapp):
    services = _services(tmp_path)
    vessel = _configured_vessel(services)
    state = MachineryFuelState(vessel.id, "ULSFO", "VLSFO", "MDO")
    services[3].save_initial_fuel_state(state)

    first = _wizard(services)
    second = _wizard(services)

    assert first._fuel_inputs["MAIN_ENGINE"].currentText() == "ULSFO"
    assert second._fuel_inputs["GENERATORS"].currentText() == "VLSFO"
    assert services[3].load_initial_fuel_state(vessel.id) == state


def test_main_window_handles_incomplete_setup_and_dashboard_explains_it(tmp_path, qapp):
    paths = AppPaths(tmp_path)
    paths.ensure_runtime_directories()
    database = Database(paths.database_file)
    database.initialize()
    VesselRepository(database).save_active("MV Partial", "7654321")
    SettingsService(paths.settings_file).save_initialization_wizard_state(seen=True, completed=False)

    window = build_main_window(paths)
    try:
        text = window.dashboard_page.status_label.text()
        assert "Current Predicted ROB unavailable" in text
        assert "Reason:" in text
        assert window.dashboard_page.resolve_button.isVisibleTo(window.dashboard_page)
    finally:
        window.close()
