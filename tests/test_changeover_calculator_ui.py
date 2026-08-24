from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QDateTime, QTimeZone, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from fuel_consumption_calculator.app import build_main_window
from fuel_consumption_calculator.calculations.fuel_changeover import calculate_fuel_changeover
from fuel_consumption_calculator.paths import AppPaths
from fuel_consumption_calculator.ui.pages import consumption_page
from fuel_consumption_calculator.ui.pages.consumption_page import ApplyChangeoverCalculationDialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _show_calculator(tmp_path, qapp, size: tuple[int, int]):
    window = build_main_window(AppPaths(tmp_path))
    window.resize(*size)
    window.show()
    window.select_page(3)
    page = window.consumption_page
    page.tabs.setCurrentIndex(2)
    qapp.processEvents()
    return window, page


def _inside(panel, widget) -> bool:
    return panel.rect().contains(widget.geometry())


@pytest.mark.parametrize("size", [(1365, 900), (1100, 750)])
def test_changeover_calculator_layout_preserves_control_geometry(tmp_path, qapp, size):
    window, page = _show_calculator(tmp_path, qapp, size)
    try:
        inputs = page.changeover_calculator_inputs
        controls = (*inputs.values(), page.changeover_calculate_button, page.changeover_reset_button)
        assert all(widget.isVisible() and widget.height() >= 30 for widget in controls)
        assert all(_inside(page.changeover_inputs_panel, widget) for widget in controls)
        assert all(_inside(page.changeover_inputs_panel, label) for label in page.changeover_input_labels.values())

        input_rows = [inputs[key].geometry() for key in ("from", "to", "target", "flow", "mass")]
        assert all(upper.bottom() < lower.top() for upper, lower in zip(input_rows, input_rows[1:]))
        assert page.changeover_calculate_button.geometry().top() > input_rows[-1].bottom()

        temperatures = (page.changeover_from_temperature, page.changeover_to_temperature)
        assert all(widget.isVisible() and widget.height() >= 30 for widget in temperatures)
        assert all(_inside(page.changeover_temperature_panel, widget) for widget in temperatures)

        result_widgets = (
            page.changeover_time_heading,
            page.changeover_result_label,
            page.changeover_minutes_label,
            page.changeover_final_label,
            page.changeover_steps_label,
            page.changeover_timestep_label,
            page.changeover_temperature_rate_label,
        )
        assert all(widget.isVisible() and widget.height() > 0 for widget in result_widgets)
        assert all(_inside(page.changeover_result_panel, widget) for widget in result_widgets)
        assert page.changeover_trace_table.isVisible() and page.changeover_trace_table.height() >= 190
        assert page.changeover_calculator_scroll.widgetResizable()
    finally:
        window.close()


def test_changeover_calculator_reference_case_is_unchanged(tmp_path, qapp):
    window, page = _show_calculator(tmp_path, qapp, (1365, 900))
    try:
        values = {"from": 1.2, "to": 0.1, "target": 0.5, "flow": 0.2, "mass": 1.0}
        for key, value in values.items():
            page.changeover_calculator_inputs[key].setValue(value)
        page._calculate_changeover()
        assert page.changeover_result_label.text() == "5.0 h"
        assert page.changeover_minutes_label.text() == "300 min"
        assert page.changeover_final_value.text() == "0.49995 %"
        assert page.changeover_steps_value.text() == "50"
        assert page.changeover_timestep_value.text() == "0.1 h"
        assert not page.apply_changeover_button.isEnabled()
        page._reset_changeover()
        assert page.changeover_result_label.text() == "-- h"
        assert page.changeover_minutes_label.text() == "-- min"
        assert not page.apply_changeover_button.isEnabled()
    finally:
        window.close()


def test_apply_dialog_requires_explicit_choices_and_keeps_sulfur_separate(monkeypatch, qapp):
    result = calculate_fuel_changeover(0.2, 1.0, 1.2, 0.1, 0.5)
    dialog = ApplyChangeoverCalculationDialog(result, 1.2, 0.1, 0.5, lambda *_: None)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))

    assert dialog.machinery_input.currentData() is None
    assert dialog.from_fuel_input.currentData() is None
    assert dialog.to_fuel_input.currentData() is None
    dialog._validate_and_accept()
    assert warnings == ["Select machinery before applying the changeover."]

    assert {dialog.machinery_input.itemData(index) for index in range(1, dialog.machinery_input.count())} == {"MAIN_ENGINE", "GENERATORS", "AUX_BOILER"}
    dialog.close()


def test_apply_dialog_recommends_utc_start_from_completion(qapp):
    result = calculate_fuel_changeover(0.2, 1.0, 1.2, 0.1, 0.5)
    dialog = ApplyChangeoverCalculationDialog(result, 1.2, 0.1, 0.5, lambda *_: None)
    completion = QDateTime.fromString("2026-08-25T12:00:00+00:00", Qt.DateFormat.ISODate)
    dialog.effective_input.setDateTime(completion)
    values = dialog.values()

    assert dialog.duration_value.text() == "5.0 h / 300 min"
    assert values["effective_at_utc"].isoformat() == "2026-08-25T12:00:00+00:00"
    assert values["recommended_start_utc"].isoformat() == "2026-08-25T07:00:00+00:00"
    assert dialog.recommended_start_value.text() == "25 Aug 2026 07:00 UTC"
    dialog.close()


def test_apply_dialog_keeps_utc_completion_out_of_host_local_timezone(qapp):
    result = calculate_fuel_changeover(0.2, 1.0, 1.2, 0.1, 0.5)
    dialog = ApplyChangeoverCalculationDialog(result, 1.2, 0.1, 0.5, lambda *_: None)
    completion = QDateTime.fromString("2026-08-25T04:56:00+00:00", Qt.DateFormat.ISODate)
    dialog.effective_input.setDateTime(completion)
    values = dialog.values()

    assert dialog.effective_input.timeZone().id().data() == QTimeZone.utc().id().data()
    assert dialog.effective_input.dateTime().toUTC().toString(Qt.DateFormat.ISODate) == "2026-08-25T04:56:00Z"
    assert values["effective_at_utc"] == datetime(2026, 8, 25, 4, 56, tzinfo=timezone.utc)
    assert values["recommended_start_utc"] == datetime(2026, 8, 24, 23, 56, tzinfo=timezone.utc)
    assert dialog.recommended_start_value.text() == "24 Aug 2026 23:56 UTC"
    dialog.close()


def test_apply_creates_one_normal_effective_changeover_and_refreshes(tmp_path, qapp, monkeypatch):
    window, page = _show_calculator(tmp_path, qapp, (1365, 900))
    try:
        vessel = page._vessel_service.configure_active_vessel("Test Vessel", "1234567")
        page.refresh()
        assert not page.apply_changeover_button.isEnabled()
        values = {"from": 1.2, "to": 0.1, "target": 0.5, "flow": 0.2, "mass": 1.0}
        for key, value in values.items():
            page.changeover_calculator_inputs[key].setValue(value)
        page._calculate_changeover()
        assert page.apply_changeover_button.isEnabled()

        refreshes = []
        monkeypatch.setattr(window.voyage_page, "refresh", lambda: refreshes.append("voyage"))
        monkeypatch.setattr(window.dashboard_page, "refresh", lambda: refreshes.append("dashboard"))

        effective_at_utc = datetime(2026, 8, 25, 4, 56, tzinfo=timezone.utc)

        class AcceptedDialog:
            def __init__(self, *args):
                self.result = args[0]

            def exec(self):
                return QDialog.DialogCode.Accepted

            def values(self):
                return {
                    "machinery": "MAIN_ENGINE",
                    "from_fuel_type": "VLSFO",
                    "to_fuel_type": "ULSFO",
                    "effective_at_utc": effective_at_utc,
                }

        monkeypatch.setattr(consumption_page, "ApplyChangeoverCalculationDialog", AcceptedDialog)
        page._apply_changeover_calculation()

        events = page._voyage_service.list_fuel_changeovers(vessel.id)
        assert len(events) == 1
        assert events[0].vessel_id == vessel.id
        assert events[0].machinery == "MAIN_ENGINE"
        assert events[0].from_fuel_type == "VLSFO"
        assert events[0].to_fuel_type == "ULSFO"
        assert events[0].effective_at_utc == effective_at_utc
        assert events[0].actual_at_utc is None
        assert refreshes == ["voyage", "dashboard"]
    finally:
        window.close()
