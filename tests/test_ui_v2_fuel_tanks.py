from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, TankCalibrationPoint
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.app import build_main_window
from fuel_consumption_calculator.paths import AppPaths
from fuel_consumption_calculator.ui_v2.dialogs.tank_sounding_survey import TankSoundingSurveyV2
from fuel_consumption_calculator.ui_v2.pages.fuel_tanks_page import FuelOilTanksPageV2


def _services(tmp_path):
    database = Database(tmp_path / "fuel.db"); database.initialize()
    return VesselService(VesselRepository(database)), FuelTankService(FuelTankRepository(database))


def _app(): return QApplication.instance() or QApplication([])


def test_v2_tanks_page_handles_empty_and_configured_tank_selection(tmp_path):
    _app(); vessel_service, service = _services(tmp_path); page = FuelOilTanksPageV2(vessel_service, service); page.refresh()
    assert page.empty_label.text() == "Configure a vessel before adding fuel oil tanks."
    vessel = vessel_service.configure_active_vessel("Test Vessel", "1234567")
    batch = service.create_fuel_batch(FuelBatch(None, vessel.id, "VLSFO-1", "VLSFO", 978))
    tank = service.create_tank(FuelTank(None, vessel.id, "HFO Deep Tank 1 Port", "BUNKER", 100, "SOUNDING", current_fuel_batch_id=batch.id))
    page.refresh(); page._select_tank(tank.id)
    assert page.empty_label.isHidden()
    assert page.inspector_name.text() == tank.name
    assert page.inspector_values["Current Batch"].text() == "VLSFO-1"
    assert [button.text() for button in page.action_buttons] == ["Edit Tank", "Update ROB", "Calibration", "Fuel / Batch"]


def test_v2_tanks_page_history_headers_are_operational(tmp_path):
    _app(); vessel_service, service = _services(tmp_path); vessel = vessel_service.configure_active_vessel("Test Vessel", "1234567")
    service.create_tank(FuelTank(None, vessel.id, "No.1 DO Serv.TK", "SERVICE", 20, "SOUNDING"))
    page = FuelOilTanksPageV2(vessel_service, service); page.refresh()
    assert [page.history_table.horizontalHeaderItem(i).text() for i in range(11)] == ["UTC", "Tank", "Type", "Reading", "Trim", "Temp °C", "Observed m³", "VCF", "Volume @15°C", "MT", "Fuel"]
    assert len(page.tank_cards) == 1


def test_v2_survey_retains_inclusion_neutral_state_totals_and_actions(tmp_path):
    _app(); vessel_service, service = _services(tmp_path); vessel = vessel_service.configure_active_vessel("Vessel", "1234567")
    batch = service.create_fuel_batch(FuelBatch(None, vessel.id, "TEST-VLSFO", "VLSFO", 978))
    tank = service.create_tank(FuelTank(None, vessel.id, "Survey Tank", "BUNKER", 100, "SOUNDING", current_fuel_batch_id=batch.id))
    service.replace_calibration_points(tank.id, [TankCalibrationPoint(None, tank.id, 0, None, 0, 0), TankCalibrationPoint(None, tank.id, 100, None, 0, 100)])
    dialog = TankSoundingSurveyV2(service, vessel.id); row = dialog._rows[0]
    assert dialog.table.horizontalHeaderItem(2).text() == "Fuel / Basis"
    assert row[6].text() == "--"
    row[1].setChecked(False); assert row[6].text() == "Excluded" and not row[3].isEnabled()
    row[1].setChecked(True); row[3].setText("50"); row[5].setText("0.985")
    assert row[6].text() == "Ready" and "VLSFO" in dialog.totals.text()
    assert dialog.use_actual.isEnabled() and dialog.save_button.text() == "Save Survey"
    assert any(button.text() == "Cancel" for button in dialog.findChildren(type(dialog.save_button)))


def test_main_window_routes_fuel_oil_tanks_to_v2(tmp_path):
    _app(); window = build_main_window(AppPaths(tmp_path / "shell"))
    window.select_page(4)
    assert type(window.fuel_tanks_page).__name__ == "FuelOilTanksPageV2"
    assert window.page_stack.currentWidget() is window.fuel_tanks_page
    window.close()
