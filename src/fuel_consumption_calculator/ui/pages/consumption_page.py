from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from fuel_consumption_calculator.calculations.consumption_engine import EventFuelConsumption
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES, OPERATING_MODES
from fuel_consumption_calculator.domain.voyage import FuelChangeoverEvent, MachineryFuelState, MACHINERY_TYPES
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.services.voyage_service import VoyageService
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader


class ConsumptionProjectionTableModel(QAbstractTableModel):
    HEADERS = ("Port", "Sea Duration", "Port Duration", "ULSFO", "VLSFO", "MDO")

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[EventFuelConsumption] = []

    def rowCount(self, parent=None) -> int:
        return len(self._rows)

    def columnCount(self, parent=None) -> int:
        return len(self.HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        row = self._rows[index.row()]
        values = (
            row.port,
            _format_duration(row.sea_hours),
            _format_duration(row.port_hours),
            _format_mt(row.consumed_mt["ULSFO"]),
            _format_mt(row.consumed_mt["VLSFO"]),
            _format_mt(row.consumed_mt["MDO"]),
        )
        return values[index.column()]

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return str(section + 1)

    def set_rows(self, rows: list[EventFuelConsumption]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()


class ConsumptionPage(QWidget):
    def __init__(
        self,
        vessel_service: VesselService,
        consumption_service: ConsumptionService,
        schedule_service: ScheduleService,
        voyage_service: VoyageService,
    ) -> None:
        super().__init__()
        self._vessel_service = vessel_service
        self._consumption_service = consumption_service
        self._schedule_service = schedule_service
        self._voyage_service = voyage_service
        self._rate_inputs: dict[tuple[str, str], QDoubleSpinBox] = {}
        self._initial_fuel_inputs: dict[str, QComboBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)
        layout.addWidget(PageHeader("Consumption", "Configure vessel fuel consumption rates."))

        self.vessel_label = QLabel("Vessel: Not configured")
        self.vessel_label.setObjectName("fieldLabel")
        layout.addWidget(self.vessel_label)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        performance_tab = QWidget()
        performance_layout = QVBoxLayout(performance_tab)
        performance_layout.addWidget(QLabel("Performance values are configured here for the detailed model. Speed/load, generator SFOC, electrical, and boiler values remain the same stored vessel settings used by Voyage Planner."))
        performance_layout.addStretch()
        self.tabs.addTab(performance_tab, "Performance")

        changeover_tab = QWidget()
        changeover_layout = QVBoxLayout(changeover_tab)
        initial_panel = QFrame()
        initial_panel.setObjectName("panel")
        initial_grid = QGridLayout(initial_panel)
        initial_grid.addWidget(QLabel("Initial Machinery Fuel State"), 0, 0, 1, 2)
        for row, (machinery, label) in enumerate((("MAIN_ENGINE", "Main Engine"), ("GENERATORS", "Generators"), ("AUX_BOILER", "Aux Boiler")), start=1):
            combo = QComboBox()
            combo.addItems(FUEL_TYPES)
            self._initial_fuel_inputs[machinery] = combo
            initial_grid.addWidget(QLabel(label), row, 0)
            initial_grid.addWidget(combo, row, 1)
        self.save_initial_fuel_button = QPushButton("Save Initial Fuel State")
        self.save_initial_fuel_button.clicked.connect(self._save_initial_fuel_state)
        initial_grid.addWidget(self.save_initial_fuel_button, 4, 1)
        changeover_layout.addWidget(initial_panel)

        edit_panel = QFrame()
        edit_panel.setObjectName("panel")
        edit_grid = QGridLayout(edit_panel)
        self.change_machinery_input = QComboBox()
        self.change_machinery_input.addItems(MACHINERY_TYPES)
        self.change_from_input = QComboBox()
        self.change_from_input.addItems(FUEL_TYPES)
        self.change_to_input = QComboBox()
        self.change_to_input.addItems(FUEL_TYPES)
        self.change_planned_input = QDateTimeEdit()
        self.change_planned_input.setCalendarPopup(True)
        self.change_planned_input.setDisplayFormat("dd MMM yyyy HH:mm")
        self.change_actual_input = QDateTimeEdit()
        self.change_actual_input.setCalendarPopup(True)
        self.change_actual_input.setDisplayFormat("dd MMM yyyy HH:mm")
        edit_grid.addWidget(QLabel("Machinery"), 0, 0)
        edit_grid.addWidget(self.change_machinery_input, 0, 1)
        edit_grid.addWidget(QLabel("From"), 0, 2)
        edit_grid.addWidget(self.change_from_input, 0, 3)
        edit_grid.addWidget(QLabel("To"), 1, 0)
        edit_grid.addWidget(self.change_to_input, 1, 1)
        edit_grid.addWidget(QLabel("Planned UTC"), 1, 2)
        edit_grid.addWidget(self.change_planned_input, 1, 3)
        edit_grid.addWidget(QLabel("Actual UTC"), 2, 0)
        edit_grid.addWidget(self.change_actual_input, 2, 1)
        self.add_changeover_button = QPushButton("Add Changeover")
        self.add_changeover_button.clicked.connect(self._add_changeover)
        self.delete_changeover_button = QPushButton("Delete Selected")
        self.delete_changeover_button.clicked.connect(self._delete_changeover)
        edit_grid.addWidget(self.add_changeover_button, 2, 2)
        edit_grid.addWidget(self.delete_changeover_button, 2, 3)
        changeover_layout.addWidget(edit_panel)
        self.changeover_table = QTableWidget(0, 6)
        self.changeover_table.setHorizontalHeaderLabels(["ID", "Machinery", "From", "To", "Effective UTC", "Status"])
        self.changeover_table.horizontalHeader().setStretchLastSection(True)
        changeover_layout.addWidget(self.changeover_table)
        self.tabs.addTab(changeover_tab, "Fuel Changeovers")

        projection_tab = QWidget()
        projection_tab_layout = QVBoxLayout(projection_tab)

        matrix = QFrame()
        matrix.setObjectName("panel")
        grid = QGridLayout(matrix)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)

        grid.addWidget(QLabel("Mode"), 0, 0)
        for column, fuel_type in enumerate(FUEL_TYPES, start=1):
            header = QLabel(f"{fuel_type} MT/day")
            header.setObjectName("fieldLabel")
            grid.addWidget(header, 0, column)

        for row, operating_mode in enumerate(OPERATING_MODES, start=1):
            mode_label = QLabel(operating_mode)
            mode_label.setObjectName("fieldLabel")
            grid.addWidget(mode_label, row, 0)
            for column, fuel_type in enumerate(FUEL_TYPES, start=1):
                spinbox = QDoubleSpinBox()
                spinbox.setDecimals(2)
                spinbox.setRange(0.0, 9999.99)
                spinbox.setSingleStep(0.25)
                spinbox.setSuffix(" MT/day")
                grid.addWidget(spinbox, row, column)
                self._rate_inputs[(operating_mode, fuel_type)] = spinbox

        fallback_tab = QWidget()
        fallback_layout = QVBoxLayout(fallback_tab)
        fallback_layout.addWidget(matrix)

        actions = QHBoxLayout()
        self.save_button = QPushButton("Save Consumption Profile")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save_profile)
        actions.addWidget(self.save_button)
        actions.addStretch()
        fallback_layout.addLayout(actions)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("mutedText")
        layout.addWidget(self.status_label)

        projection = QFrame()
        projection.setObjectName("panel")
        projection_layout = QVBoxLayout(projection)
        projection_layout.setContentsMargins(18, 16, 18, 16)
        projection_layout.setSpacing(10)
        projection_title = QLabel("PROJECTED SCHEDULE CONSUMPTION")
        projection_title.setObjectName("fieldLabel")
        projection_layout.addWidget(projection_title)

        self.projection_table_model = ConsumptionProjectionTableModel()
        self.projection_table = QTableView()
        self.projection_table.setModel(self.projection_table_model)
        self.projection_table.setAlternatingRowColors(True)
        self.projection_table.horizontalHeader().setStretchLastSection(True)
        projection_layout.addWidget(self.projection_table)

        self.totals_label = QLabel("ULSFO Total: 0.00 MT   |   VLSFO Total: 0.00 MT   |   MDO Total: 0.00 MT")
        self.totals_label.setObjectName("fieldLabel")
        projection_layout.addWidget(self.totals_label)
        projection_tab_layout.addWidget(projection, 1)
        self.tabs.addTab(projection_tab, "Projection")
        self.tabs.addTab(fallback_tab, "Fixed-Rate Fallback")

        layout.addStretch()

        self.refresh()

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self.vessel_label.setText("Vessel: Not configured")
            self.save_button.setEnabled(False)
            self._set_inputs_enabled(False)
            self._set_changeover_inputs_enabled(False)
            self._set_rates_to_zero()
            self._clear_projection("No vessel configured.")
            self.status_label.setText("Configure a vessel before saving consumption rates.")
            return

        self.vessel_label.setText(f"Vessel: {vessel.name}  |  IMO {vessel.imo}")
        self.save_button.setEnabled(True)
        self._set_inputs_enabled(True)
        self._set_changeover_inputs_enabled(True)
        profile = self._consumption_service.load_profile(vessel.id)
        for key, spinbox in self._rate_inputs.items():
            spinbox.setValue(profile.rate_for(*key))
        self._refresh_projection(vessel.id)
        self._refresh_fuel_state(vessel.id)
        self._refresh_changeovers(vessel.id)
        self.status_label.setText("Consumption profile loaded.")

    def _save_profile(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            QMessageBox.warning(self, "Vessel required", "Configure a vessel before saving consumption rates.")
            return

        rates = {
            key: spinbox.value()
            for key, spinbox in self._rate_inputs.items()
        }
        try:
            profile = self._consumption_service.build_profile(vessel.id, rates)
            saved_profile = self._consumption_service.save_profile(profile)
        except Exception as exc:
            QMessageBox.warning(self, "Consumption profile not saved", str(exc))
            return

        for key, spinbox in self._rate_inputs.items():
            spinbox.setValue(saved_profile.rate_for(*key))
        self._refresh_projection(vessel.id)
        self.status_label.setText("Consumption profile saved.")

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for spinbox in self._rate_inputs.values():
            spinbox.setEnabled(enabled)

    def _set_rates_to_zero(self) -> None:
        for spinbox in self._rate_inputs.values():
            spinbox.setValue(0.0)

    def _refresh_projection(self, vessel_id: int) -> None:
        timeline = self._schedule_service.get_timeline(vessel_id)
        if not timeline.rows:
            self._clear_projection("No schedule events available.")
            return
        try:
            result = self._consumption_service.calculate_schedule_consumption(vessel_id, timeline)
        except Exception as exc:
            self._clear_projection(str(exc))
            return
        self.projection_table_model.set_rows(result.rows)
        self.totals_label.setText(
            "ULSFO Total: "
            f"{_format_mt(result.totals_mt['ULSFO'])}   |   "
            "VLSFO Total: "
            f"{_format_mt(result.totals_mt['VLSFO'])}   |   "
            "MDO Total: "
            f"{_format_mt(result.totals_mt['MDO'])}"
        )

    def _clear_projection(self, message: str) -> None:
        self.projection_table_model.set_rows([])
        self.totals_label.setText(
            "ULSFO Total: 0.00 MT   |   VLSFO Total: 0.00 MT   |   MDO Total: 0.00 MT"
            f"   |   {message}"
        )

    def _set_changeover_inputs_enabled(self, enabled: bool) -> None:
        for widget in [*self._initial_fuel_inputs.values(), self.save_initial_fuel_button, self.add_changeover_button, self.delete_changeover_button]:
            widget.setEnabled(enabled)

    def _refresh_fuel_state(self, vessel_id: int) -> None:
        state = self._voyage_service.load_initial_fuel_state(vessel_id)
        self._initial_fuel_inputs["MAIN_ENGINE"].setCurrentText(state.main_engine_fuel_type)
        self._initial_fuel_inputs["GENERATORS"].setCurrentText(state.generators_fuel_type)
        self._initial_fuel_inputs["AUX_BOILER"].setCurrentText(state.aux_boiler_fuel_type)

    def _save_initial_fuel_state(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            return
        state = MachineryFuelState(
            vessel_id=vessel.id,
            main_engine_fuel_type=self._initial_fuel_inputs["MAIN_ENGINE"].currentText(),
            generators_fuel_type=self._initial_fuel_inputs["GENERATORS"].currentText(),
            aux_boiler_fuel_type=self._initial_fuel_inputs["AUX_BOILER"].currentText(),
        )
        self._voyage_service.save_initial_fuel_state(state)
        self._refresh_projection(vessel.id)
        self.status_label.setText("Initial machinery fuel state saved.")

    def _refresh_changeovers(self, vessel_id: int) -> None:
        rows = self._voyage_service.list_fuel_changeovers(vessel_id)
        self.changeover_table.setRowCount(len(rows))
        for row_index, event in enumerate(rows):
            values = [
                str(event.id or ""),
                event.machinery,
                event.from_fuel_type,
                event.to_fuel_type,
                event.effective_at_utc.isoformat(timespec="minutes"),
                "ACTUAL" if event.actual_at_utc else event.status,
            ]
            for column, value in enumerate(values):
                self.changeover_table.setItem(row_index, column, QTableWidgetItem(value))

    def _add_changeover(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            return
        event = FuelChangeoverEvent(
            id=None,
            vessel_id=vessel.id,
            machinery=self.change_machinery_input.currentText(),
            from_fuel_type=self.change_from_input.currentText(),
            to_fuel_type=self.change_to_input.currentText(),
            planned_at_utc=self.change_planned_input.dateTime().toPython(),
            actual_at_utc=self.change_actual_input.dateTime().toPython(),
            time_basis="UTC",
            status="PLANNED",
        )
        try:
            self._voyage_service.save_fuel_changeover(event)
        except Exception as exc:
            QMessageBox.warning(self, "Changeover not saved", str(exc))
            return
        self._refresh_changeovers(vessel.id)
        self._refresh_projection(vessel.id)
        self.status_label.setText("Fuel changeover saved.")

    def _delete_changeover(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            return
        selected = self.changeover_table.selectedItems()
        if not selected:
            QMessageBox.information(self, "Select changeover", "Select a fuel changeover first.")
            return
        event_id = int(self.changeover_table.item(selected[0].row(), 0).text())
        self._voyage_service.delete_fuel_changeover(vessel.id, event_id)
        self._refresh_changeovers(vessel.id)
        self._refresh_projection(vessel.id)
        self.status_label.setText("Fuel changeover deleted.")


def _format_mt(value: float) -> str:
    return f"{value:.2f} MT"


def _format_duration(hours: float) -> str:
    total_minutes = round(hours * 60)
    days, remainder = divmod(total_minutes, 24 * 60)
    whole_hours, minutes = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days} d")
    if whole_hours or days:
        parts.append(f"{whole_hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    return " ".join(parts) if parts else "0 h"
