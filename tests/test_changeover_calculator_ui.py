from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from fuel_consumption_calculator.app import build_main_window
from fuel_consumption_calculator.paths import AppPaths


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
        page._reset_changeover()
        assert page.changeover_result_label.text() == "-- h"
        assert page.changeover_minutes_label.text() == "-- min"
    finally:
        window.close()
