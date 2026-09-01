from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea

from fuel_consumption_calculator.app import build_main_window
from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, TankCalibrationPoint
from fuel_consumption_calculator.paths import AppPaths
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.ui.pages.fuel_tanks_page import (
    VESSEL_TANK_SET,
    FuelTanksPage,
    TankSoundingSurveyDialog,
    InternalTransferDialog,
    TankDialog,
    VesselTankSetDialog,
    _position_for_tank,
    _short_display_name,
)
from fuel_consumption_calculator.ui.pages.fuel_tank_operational_dialogs import (
    CalibrationDialog,
    UpdateTankROBDialog,
    export_calibration_xlsx,
    generate_calibration_points,
    import_calibration_xlsx,
)


def test_tank_sounding_survey_dialog_constructs_with_measurement_types(tmp_path, qapp):
    vessel_service, service = _services(tmp_path)
    vessel = vessel_service.configure_active_vessel("Vessel", "1234567")
    tank = service.create_tank(FuelTank(None, vessel.id, "Survey Tank", "BUNKER", 100, "ULLAGE"))
    service.replace_calibration_points(tank.id, [TankCalibrationPoint(None, tank.id, 0, 0, 0, 0)])
    dialog = TankSoundingSurveyDialog(service, vessel.id)
    kind = dialog._rows[0][2]
    assert [kind.itemText(index) for index in range(kind.count())] == ["SOUNDING", "ULLAGE"]
    assert kind.currentText() == "ULLAGE"


def test_survey_table_keeps_untouched_rows_neutral_and_excluded_rows_non_blocking(tmp_path, qapp):
    vessel_service, service = _services(tmp_path)
    vessel = vessel_service.configure_active_vessel("Vessel", "1234567")
    tank = service.create_tank(FuelTank(None, vessel.id, "Survey Tank", "BUNKER", 100, "SOUNDING"))
    service.replace_calibration_points(tank.id, [TankCalibrationPoint(None, tank.id, 0, 0, 0, 0)])
    dialog = TankSoundingSurveyDialog(service, vessel.id)
    row = dialog._rows[0]
    assert dialog.table.columnCount() == 10
    assert row[6].text() == "--"
    row[1].setChecked(False)
    assert row[6].text() == "Excluded"
    assert not row[3].isEnabled()


def test_survey_table_calculates_volume_mass_totals_and_completeness(tmp_path, qapp):
    vessel_service, service = _services(tmp_path)
    vessel = vessel_service.configure_active_vessel("Vessel", "1234567")
    batch = service.create_fuel_batch(FuelBatch(None, vessel.id, "TEST-VLSFO", "VLSFO", 978))
    tank = service.create_tank(FuelTank(None, vessel.id, "Survey Tank", "BUNKER", 100, "SOUNDING", current_fuel_batch_id=batch.id))
    service.replace_calibration_points(tank.id, [TankCalibrationPoint(None, tank.id, 0, 0, 0, 0), TankCalibrationPoint(None, tank.id, 100, None, 0, 100)])
    dialog = TankSoundingSurveyDialog(service, vessel.id)
    row = dialog._rows[0]
    row[3].setText("50")
    assert row[8].text() == "50.000"
    assert row[6].text() == "VCF needed for MT"
    assert not dialog.use_actual.isEnabled()
    row[5].setText("0.985")
    assert row[9].text() != "--"
    assert row[6].text() == "Ready"
    assert "VLSFO" in dialog.totals.text()
    assert dialog.use_actual.isEnabled()
    assert dialog.save_button.text() == "Save Survey"


def test_internal_transfer_action_and_dialog_construct(tmp_path, qapp):
    vessel_service, service = _services(tmp_path)
    vessel = vessel_service.configure_active_vessel("Vessel", "1234567")
    page = FuelTanksPage(vessel_service, service)
    page.refresh()
    assert page.internal_transfer_button.text() == "Internal Transfer"
    assert page.internal_transfer_button.isEnabled()
    dialog = InternalTransferDialog(service, vessel.id)
    assert dialog.windowTitle() == "Internal Transfer"
    assert dialog.history_table.columnCount() == 7


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _services(tmp_path):
    database = Database(tmp_path / "fuel.db")
    database.initialize()
    return VesselService(VesselRepository(database)), FuelTankService(FuelTankRepository(database))


def test_fuel_tanks_page_handles_no_vessel_and_empty_tanks(tmp_path, qapp):
    vessel_service, tank_service = _services(tmp_path)
    page = FuelTanksPage(vessel_service, tank_service)
    page.refresh()
    assert page.empty_label.text() == "Configure a vessel before adding fuel oil tanks."
    assert not page.add_tank_button.isEnabled()
    vessel_service.configure_active_vessel("Test Vessel", "1234567")
    page.refresh()
    assert page.empty_label.text() == "No fuel oil tanks configured."
    assert page.add_tank_button.isEnabled()


def test_selected_tank_inspector_uses_existing_tank_data(tmp_path, qapp):
    vessel_service, tank_service = _services(tmp_path)
    vessel = vessel_service.configure_active_vessel("Test Vessel", "1234567")
    batch = tank_service.create_fuel_batch(FuelBatch(None, vessel.id, "VLSFO-1", "VLSFO", 978))
    tank = tank_service.create_tank(FuelTank(None, vessel.id, "HFO Deep Tank 1 Port", "BUNKER", 100, "SOUNDING", current_fuel_batch_id=batch.id))
    page = FuelTanksPage(vessel_service, tank_service)
    page.refresh()

    page._select_tank(tank.id)

    assert page.inspector_name.text() == tank.name
    assert page.inspector_fuel.text() == "VLSFO"
    assert page.inspector_values["Current Batch"].text() == "VLSFO-1"
    assert page.update_rob_button.isEnabled()


def test_tank_dialog_add_and_edit_refreshes_cards(tmp_path, qapp):
    vessel_service, tank_service = _services(tmp_path)
    vessel = vessel_service.configure_active_vessel("Test Vessel", "1234567")
    dialog = TankDialog(tank_service, vessel.id)
    dialog.name_input.setText("No. 1 P/S")
    dialog.capacity_input.setValue(500)
    dialog._save()
    tank = tank_service.list_tanks(vessel.id)[0]
    assert tank.name == "No. 1 P/S"
    assert tank.current_fuel_batch_id is None
    edit_dialog = TankDialog(tank_service, vessel.id, tank)
    edit_dialog.name_input.setText("No. 1 Port")
    edit_dialog._save()
    page = FuelTanksPage(vessel_service, tank_service)
    page.refresh()
    assert tank_service.get_tank(tank.id).name == "No. 1 Port"
    assert len(page.tank_cards) == 1
    assert not hasattr(dialog, "measurement_input")


def test_app_and_main_window_construct_with_fuel_tanks_page(tmp_path, qapp):
    paths = AppPaths(tmp_path)
    window = build_main_window(paths)
    assert window.PAGE_NAMES[4] == "Fuel Oil Tanks"
    assert window.page_stack.widget(4) is window.fuel_tanks_page
    window.close()


@pytest.mark.parametrize(
    ("name", "position"),
    [
        ("HFO DEEP TK 1S", "DEEP_1S"),
        ("HFO DEEP TK(1S)", "DEEP_1S"),
        ("HFO Deep Tank 1 STBD", "DEEP_1S"),
        ("HFO DEEP TANK 1 PORT", "DEEP_1P"),
        ("HFO SETTLING TANK", "HFO_SETT"),
        ("LSHFO SERVICE TANK", "ULSFO_SERV"),
        ("NO.2 MDO STORAGE TANK", "MDO_2_STOR"),
    ],
)
def test_tank_aliases_resolve_to_known_positions(name, position):
    assert _position_for_tank(name) == position


def test_known_positions_and_other_tanks_render_without_placeholders(tmp_path, qapp):
    vessel_service, tank_service = _services(tmp_path)
    vessel = vessel_service.configure_active_vessel("Test Vessel", "1234567")
    for name in ("No. 1 DO Serv.TK", "HFO Deep Tank 1 STBD", "Unmatched Drain Tank"):
        tank_service.create_tank(FuelTank(None, vessel.id, name, "BUNKER", 100, "SOUNDING"))
    page = FuelTanksPage(vessel_service, tank_service)
    page.refresh()
    assert len(page.tank_cards) == 3
    assert any(label.text() == "OTHER TANKS" for label in page.findChildren(type(page.vessel_label)))


def test_compact_scrollable_tank_strip_and_short_labels(tmp_path, qapp):
    vessel_service, tank_service = _services(tmp_path)
    vessel = vessel_service.configure_active_vessel("Test Vessel", "1234567")
    for name in ("No. 1 DO Serv.TK", "HFO Deep Tank 1 STBD", "OVFLW TK CH"):
        tank_service.create_tank(FuelTank(None, vessel.id, name, "BUNKER", 100, "SOUNDING"))
    page = FuelTanksPage(vessel_service, tank_service)
    page.refresh()
    assert isinstance(page.tank_strip, QScrollArea)
    assert page.tank_strip.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert page.tank_strip.widgetResizable() is False
    by_name = {card.toolTip(): card for card in page.tank_cards}
    assert (by_name["No. 1 DO Serv.TK"].width(), by_name["No. 1 DO Serv.TK"].height()) == (120, 72)
    assert (by_name["HFO Deep Tank 1 STBD"].width(), by_name["HFO Deep Tank 1 STBD"].height()) == (152, 152)
    assert (by_name["OVFLW TK CH"].width(), by_name["OVFLW TK CH"].height()) == (128, 142)
    assert _short_display_name("HFO DEEP TANK 1 STBD") == "1S"
    assert _short_display_name("NO.1 DO SERV.TK") == "DO SVC 1"
    assert _short_display_name("OVFLW TK CH") == "CH OVFLW"


def test_populated_strip_publishes_nonzero_fixed_content_geometry(tmp_path, qapp):
    vessel_service, tank_service = _services(tmp_path)
    vessel = vessel_service.configure_active_vessel("Test Vessel", "1234567")
    for name, tank_type, _receiving in VESSEL_TANK_SET:
        tank_service.create_tank(FuelTank(None, vessel.id, name, tank_type, 100, "SOUNDING"))
    page = FuelTanksPage(vessel_service, tank_service)
    page.resize(900, 700)
    page.show()
    page.refresh()
    qapp.processEvents()
    assert len(page.tank_cards) == 16
    assert {"HFO DEEP TK 1P", "OVFLW TK CH"}.issubset({card.toolTip() for card in page.tank_cards})
    assert page.strip_content.width() > 0 and page.strip_content.height() > 0
    assert page.strip_content.width() >= page.arrangement_layout.sizeHint().width()
    assert page.strip_content.height() >= page.arrangement_layout.sizeHint().height()
    assert page.tank_strip.widgetResizable() is False
    assert page.tank_strip.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    by_name = {card.toolTip(): card for card in page.tank_cards}
    assert by_name["HFO DEEP TK 1P"].height() > by_name["HFO SETT.TK"].height()
    assert by_name["HFO DEEP TK 1P"].width() > by_name["NO.1 DO SERV.TK"].width()
    page._select_tank(by_name["HFO DEEP TK 1P"]._tank_id)
    assert page.edit_tank_button.isEnabled()
    page.close()


def test_bulk_tank_set_defaults_and_capacity_requirement(tmp_path, qapp):
    vessel_service, tank_service = _services(tmp_path)
    vessel = vessel_service.configure_active_vessel("Test Vessel", "1234567")
    dialog = VesselTankSetDialog(tank_service, vessel.id)
    assert dialog.tank_table.rowCount() == 16
    defaults = {name: (tank_type, receiving) for name, tank_type, receiving in VESSEL_TANK_SET}
    assert defaults["HFO DEEP TK 1P"] == ("BUNKER", True)
    assert defaults["NO.1 DO STOR.TK"] == ("BUNKER", True)
    assert defaults["HFO SETT.TK"] == ("SETTLING", False)
    assert defaults["NO.1 DO SERV.TK"] == ("SERVICE", False)
    assert defaults["OVFLW TK ER"] == ("OTHER", False)
    with pytest.raises(ValueError, match="capacity greater than 0"):
        dialog.create_selected_tanks()


def test_bulk_tank_set_creates_selected_tanks_and_skips_alias_duplicates(tmp_path, qapp):
    vessel_service, tank_service = _services(tmp_path)
    vessel = vessel_service.configure_active_vessel("Test Vessel", "1234567")
    existing = tank_service.create_tank(FuelTank(None, vessel.id, "HFO Deep Tank 1 STBD", "BUNKER", 300, "SOUNDING"))
    dialog = VesselTankSetDialog(tank_service, vessel.id)
    selected_names = {"HFO DEEP TK 1S", "HFO DEEP TK 1P", "HFO SETT.TK"}
    for row, (name, _, _) in enumerate(VESSEL_TANK_SET):
        include, capacity, _receiving = dialog.row_controls[row]
        include.setChecked(name in selected_names)
        if name in selected_names:
            capacity.setValue(250)
    created, already_existed = dialog.create_selected_tanks()
    tanks = tank_service.list_tanks(vessel.id, include_inactive=True)
    assert (created, already_existed) == (2, 1)
    assert existing in tanks
    assert {tank.name for tank in tanks} == {"HFO Deep Tank 1 STBD", "HFO DEEP TK 1P", "HFO SETT.TK"}
    assert tank_service.list_fuel_batches(vessel.id) == []
    assert all(tank_service.list_sounding_history(tank.id) == [] for tank in tanks)


def test_calibration_dialog_excel_round_trip_generator_and_update_rob(tmp_path, qapp):
    vessel_service, tank_service = _services(tmp_path)
    vessel = vessel_service.configure_active_vessel("Test Vessel", "1234567")
    tank = tank_service.create_tank(FuelTank(None, vessel.id, "HFO DEEP TK 1P", "BUNKER", 100, "ULLAGE"))
    points = generate_calibration_points(tank.id, 100, 50, 1, 1, 1, 100, 90, 110)
    assert {point.trim_m for point in points} == {-1, 0, 1}
    workbook = tmp_path / "calibration.xlsx"
    export_calibration_xlsx(workbook, tank, points)
    imported = import_calibration_xlsx(workbook, tank.id)
    assert len(imported) == len(points)
    dialog = CalibrationDialog(tank_service, tank)
    dialog.set_points(imported)
    dialog.save()
    assert len(tank_service.list_calibration_points(tank.id)) == len(points)
    rob = UpdateTankROBDialog(tank_service, tank)
    assert set(rob.types) == {"SOUNDING", "ULLAGE"}
    rob.type.setCurrentText("SOUNDING")
    rob.reading.setText("50"); rob.trim.setText("0")
    rob.update_preview()
    assert "50.000" in rob.preview.text()
