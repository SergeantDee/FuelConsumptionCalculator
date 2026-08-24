from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QAbstractTableModel, QDateTime, QTimeZone, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from fuel_consumption_calculator.calculations.consumption_engine import EventFuelConsumption
from fuel_consumption_calculator.calculations.fuel_changeover import FuelChangeoverCalculationError, calculate_fuel_changeover
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.voyage import FuelChangeoverEvent, GeneratorSfocPoint, MachineryFuelState, MACHINERY_TYPES, MainEngineSfocPoint, VesselEnergyConfig
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.services.voyage_service import VoyageService
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader


class ConsumptionProjectionTableModel(QAbstractTableModel):
    HEADERS = ("Port", "Sea Duration", "Port Duration", "ULSFO", "VLSFO", "MDO", "Issue / Reason")

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[EventFuelConsumption] = []
        self._issues: dict[int, str] = {}

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
            self._issues.get(row.event_id, ""),
        )
        return values[index.column()]

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return str(section + 1)

    def set_rows(self, rows: list[EventFuelConsumption], issues: dict[int, str] | None = None) -> None:
        self.beginResetModel()
        self._rows = rows
        self._issues = dict(issues or {})
        self.endResetModel()


class ConsumptionPage(QWidget):
    changeover_saved = Signal()

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
        self._initial_fuel_inputs: dict[str, QComboBox] = {}
        self._energy_inputs: dict[str, QDoubleSpinBox] = {}
        self._maneuvering_rate_inputs: dict[str, QLineEdit] = {}
        self._main_engine_sfoc_inputs: list[tuple[QDoubleSpinBox, QDoubleSpinBox]] = []
        self._sfoc_inputs: list[tuple[QDoubleSpinBox, QDoubleSpinBox]] = []
        self._changeover_result = None

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
        performance_root = QVBoxLayout(performance_tab)
        performance_scroll = QScrollArea()
        performance_scroll.setWidgetResizable(True)
        performance_scroll.setFrameShape(QFrame.Shape.NoFrame)
        performance_content = QWidget()
        performance_layout = QVBoxLayout(performance_content)
        performance_layout.setSpacing(12)
        performance_layout.addWidget(_help_label("Detailed vessel-performance data used by Voyage Planner, Projection, ROB, and Bunker calculations."))
        engine_panel = QFrame()
        engine_panel.setObjectName("panel")
        engine_grid = QGridLayout(engine_panel)
        engine_grid.setContentsMargins(18, 16, 18, 16)
        engine_grid.addWidget(_section_label("Main Engine Performance"), 0, 0, 1, 5)
        engine_grid.addWidget(_help_label("Workbook-derived model: Speed -> RPM -> Power -> ME load; ME fuel = power × SFOC / 1,000,000."), 1, 0, 1, 5)
        for column, (label, key) in enumerate((
            ("Slip %", "main_engine_slip_percent"),
            ("Speed/RPM Factor", "speed_rpm_factor"),
            ("Power Coefficient", "power_coefficient"),
            ("MCR kW", "mcr_power_kw"),
        )):
            engine_grid.addWidget(QLabel(label), 2, column)
            spinbox = _spinbox("" if key != "main_engine_slip_percent" else " %", 0, 999999, 1)
            if key in ("speed_rpm_factor", "power_coefficient"):
                spinbox.setDecimals(7)
                spinbox.setSingleStep(0.0001)
            engine_grid.addWidget(spinbox, 3, column)
            self._energy_inputs[key] = spinbox
        for column, header in enumerate(("ME Load %", "ME SFOC g/kWh", "ME Load %", "ME SFOC g/kWh")):
            engine_grid.addWidget(QLabel(header), 4, column)
        for index in range(17):
            load_input = _spinbox(" %", 0, 200, 5)
            sfoc_input = _spinbox(" g/kWh", 0, 9999, 1)
            row = 5 + index // 2
            column = 0 if index % 2 == 0 else 2
            engine_grid.addWidget(load_input, row, column)
            engine_grid.addWidget(sfoc_input, row, column + 1)
            self._main_engine_sfoc_inputs.append((load_input, sfoc_input))
        performance_layout.addWidget(engine_panel)

        generator_panel = QFrame()
        generator_panel.setObjectName("panel")
        generator_grid = QGridLayout(generator_panel)
        generator_grid.setContentsMargins(18, 16, 18, 16)
        generator_grid.addWidget(_section_label("Generator Performance"), 0, 0, 1, 4)
        for label, key, column in (("DG Rated kW", "generator_rated_kw", 0), ("Port DG Count", "port_running_generators", 1), ("Sea DG Count", "sea_running_generators", 2)):
            generator_grid.addWidget(QLabel(label), 1, column)
            spinbox = _spinbox("", 0, 999999, 1)
            generator_grid.addWidget(spinbox, 2, column)
            self._energy_inputs[key] = spinbox
        generator_grid.addWidget(QLabel("DG Load %"), 3, 0)
        generator_grid.addWidget(QLabel("SFOC g/kWh"), 3, 1)
        for row in range(3):
            load_input = _spinbox(" %", 0, 200, 5)
            sfoc_input = _spinbox(" g/kWh", 0, 9999, 1)
            generator_grid.addWidget(load_input, row + 4, 0)
            generator_grid.addWidget(sfoc_input, row + 4, 1)
            self._sfoc_inputs.append((load_input, sfoc_input))
        performance_layout.addWidget(generator_panel)

        electrical_panel = QFrame()
        electrical_panel.setObjectName("panel")
        electrical_grid = QGridLayout(electrical_panel)
        electrical_grid.setContentsMargins(18, 16, 18, 16)
        electrical_grid.addWidget(_section_label("Electrical Load / Auxiliary Boiler"), 0, 0, 1, 4)
        for label, key, column in (("Port Base kW", "port_base_load_kw", 0), ("Sea Base kW", "sea_base_load_kw", 1), ("Legacy Reefer kW/unit", "reefer_kw_per_unit", 2), ("Aux Boiler MT/h", "aux_boiler_mt_per_hour", 3)):
            electrical_grid.addWidget(QLabel(label), 1, column)
            spinbox = _spinbox("", 0, 999999, 1)
            electrical_grid.addWidget(spinbox, 2, column)
            self._energy_inputs[key] = spinbox
        for label, key, column in (("Port Ambient °C", "port_ambient_c", 0), ("Sea Ambient °C", "sea_ambient_c", 1)):
            electrical_grid.addWidget(QLabel(label), 5, column)
            spinbox = _spinbox(" °C", -50, 80, 1)
            electrical_grid.addWidget(spinbox, 6, column)
            self._energy_inputs[key] = spinbox
        for label, key, column in (
            ("ME Maneuvering MT/h", "maneuvering_main_engine_mt_per_hour", 0),
            ("DG Maneuvering MT/h", "maneuvering_generators_mt_per_hour", 1),
            ("Aux Boiler Maneuvering MT/h", "maneuvering_aux_boiler_mt_per_hour", 2),
        ):
            electrical_grid.addWidget(QLabel(label), 7, column)
            input_widget = QLineEdit()
            input_widget.setPlaceholderText("Not configured")
            electrical_grid.addWidget(input_widget, 8, column)
            self._maneuvering_rate_inputs[key] = input_widget
        self.generator_fuel_combo = QComboBox()
        self.generator_fuel_combo.addItems(FUEL_TYPES)
        self.boiler_fuel_combo = QComboBox()
        self.boiler_fuel_combo.addItems(FUEL_TYPES)
        electrical_grid.addWidget(QLabel("DG Fuel"), 3, 0)
        electrical_grid.addWidget(self.generator_fuel_combo, 4, 0)
        electrical_grid.addWidget(QLabel("Boiler Fuel"), 3, 1)
        electrical_grid.addWidget(self.boiler_fuel_combo, 4, 1)
        self.save_performance_button = QPushButton("Save Performance Settings")
        self.save_performance_button.setObjectName("primaryButton")
        self.save_performance_button.clicked.connect(self._save_performance)
        electrical_grid.addWidget(self.save_performance_button, 4, 2, 1, 2)
        performance_layout.addWidget(electrical_panel)
        performance_layout.addStretch()
        performance_scroll.setWidget(performance_content)
        performance_root.addWidget(performance_scroll)
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
        self.change_actual_enabled = QCheckBox("Actual time entered")
        self.change_actual_enabled.toggled.connect(self.change_actual_input.setEnabled)
        self.change_actual_input.setEnabled(False)
        self.change_planned_input.setDateTime(QDateTime.currentDateTime())
        self.change_actual_input.setDateTime(QDateTime.currentDateTime())
        edit_grid.addWidget(QLabel("Machinery"), 0, 0)
        edit_grid.addWidget(self.change_machinery_input, 0, 1)
        edit_grid.addWidget(QLabel("From"), 0, 2)
        edit_grid.addWidget(self.change_from_input, 0, 3)
        edit_grid.addWidget(QLabel("To"), 1, 0)
        edit_grid.addWidget(self.change_to_input, 1, 1)
        edit_grid.addWidget(QLabel("Planned UTC"), 1, 2)
        edit_grid.addWidget(self.change_planned_input, 1, 3)
        edit_grid.addWidget(self.change_actual_enabled, 2, 0)
        edit_grid.addWidget(self.change_actual_input, 2, 1)
        self.add_changeover_button = QPushButton("Add Changeover")
        self.add_changeover_button.clicked.connect(self._add_changeover)
        self.delete_changeover_button = QPushButton("Delete Selected")
        self.delete_changeover_button.setObjectName("dangerButton")
        self.delete_changeover_button.clicked.connect(self._delete_changeover)
        edit_grid.addWidget(self.add_changeover_button, 2, 2)
        edit_grid.addWidget(self.delete_changeover_button, 2, 3)
        changeover_layout.addWidget(edit_panel)
        self.changeover_table = QTableWidget(0, 7)
        self.changeover_table.setHorizontalHeaderLabels(["ID", "Machinery", "From", "To", "Planned UTC", "Actual UTC", "Status"])
        self.changeover_table.verticalHeader().setDefaultSectionSize(32)
        self.changeover_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        changeover_layout.addWidget(self.changeover_table)
        self.tabs.addTab(changeover_tab, "Fuel Changeovers")

        calculator_tab = QWidget()
        calculator_root = QVBoxLayout(calculator_tab)
        calculator_root.setContentsMargins(0, 0, 0, 0)
        self.changeover_calculator_scroll = QScrollArea()
        self.changeover_calculator_scroll.setWidgetResizable(True)
        self.changeover_calculator_scroll.setFrameShape(QFrame.Shape.NoFrame)
        calculator_content = QWidget()
        calculator_layout = QVBoxLayout(calculator_content)
        calculator_layout.setContentsMargins(18, 18, 18, 18)
        calculator_layout.setSpacing(10)
        calculator_layout.addWidget(_section_label("CHANGEOVER CALCULATOR")); calculator_layout.addWidget(_help_label("0.1 h complete-mixing model based on verified LR/FOBAS calculator behavior.")); calculator_layout.addWidget(_help_label("0.10% and 0.50% replacement fuels use verified internal reference offsets."))
        input_row = QHBoxLayout()
        input_row.setSpacing(12)
        self.changeover_inputs_panel = QFrame()
        self.changeover_inputs_panel.setObjectName("panel")
        calculator_grid = QGridLayout(self.changeover_inputs_panel)
        calculator_grid.setContentsMargins(18, 16, 18, 16)
        calculator_grid.setHorizontalSpacing(16)
        calculator_grid.setVerticalSpacing(10)
        calculator_grid.addWidget(_section_label("CHANGEOVER INPUTS"), 0, 0, 1, 2)
        self.changeover_calculator_inputs = {}
        self.changeover_input_labels = {}
        for row, (label, key) in enumerate((("FROM Sulphur (%)", "from"), ("TO Sulphur (%)", "to"), ("Target Sulphur (%)", "target"), ("Fuel Flow (MT/h)", "flow"), ("System Quantity (MT)", "mass")), 1):
            input_label = QLabel(label)
            input_widget = _spinbox("", 0, 999999, 1)
            input_widget.setDecimals(5)
            input_widget.setSingleStep(.01)
            input_widget.setMinimumHeight(32)
            calculator_grid.addWidget(input_label, row, 0)
            calculator_grid.addWidget(input_widget, row, 1)
            self.changeover_input_labels[key] = input_label
            self.changeover_calculator_inputs[key] = input_widget
        self.changeover_calculate_button = QPushButton("Calculate Changeover")
        self.changeover_calculate_button.setObjectName("primaryButton")
        self.changeover_calculate_button.setMinimumHeight(32)
        self.changeover_calculate_button.clicked.connect(self._calculate_changeover)
        self.changeover_reset_button = QPushButton("Reset")
        self.changeover_reset_button.setMinimumHeight(32)
        self.changeover_reset_button.clicked.connect(self._reset_changeover)
        calculator_grid.addWidget(self.changeover_calculate_button, 6, 0)
        calculator_grid.addWidget(self.changeover_reset_button, 6, 1)
        self.apply_changeover_button = QPushButton("Apply to Fuel Changeovers...")
        self.apply_changeover_button.setEnabled(False)
        self.apply_changeover_button.clicked.connect(self._apply_changeover_calculation)
        calculator_grid.addWidget(self.apply_changeover_button, 7, 0, 1, 2)
        calculator_grid.setColumnStretch(0, 1)
        calculator_grid.setColumnStretch(1, 1)
        input_row.addWidget(self.changeover_inputs_panel, 3)

        self.changeover_temperature_panel = QFrame()
        self.changeover_temperature_panel.setObjectName("panel")
        temp_grid = QGridLayout(self.changeover_temperature_panel)
        temp_grid.setContentsMargins(18, 16, 18, 16)
        temp_grid.setHorizontalSpacing(16)
        temp_grid.setVerticalSpacing(10)
        temp_grid.addWidget(_section_label("TEMPERATURE ADVISORY"), 0, 0, 1, 2)
        self.changeover_from_temperature = QLineEdit()
        self.changeover_to_temperature = QLineEdit()
        self.changeover_from_temperature.setMinimumHeight(32)
        self.changeover_to_temperature.setMinimumHeight(32)
        self.changeover_from_temperature_label = QLabel("FROM Temperature (C)")
        self.changeover_to_temperature_label = QLabel("TO Temperature (C)")
        temp_grid.addWidget(self.changeover_from_temperature_label, 1, 0)
        temp_grid.addWidget(self.changeover_from_temperature, 1, 1)
        temp_grid.addWidget(self.changeover_to_temperature_label, 2, 0)
        temp_grid.addWidget(self.changeover_to_temperature, 2, 1)
        temp_grid.addWidget(_help_label("Advisory only - does not affect changeover time."), 3, 0, 1, 2)
        temp_grid.setColumnStretch(0, 1)
        temp_grid.setColumnStretch(1, 1)
        input_row.addWidget(self.changeover_temperature_panel, 2, Qt.AlignmentFlag.AlignTop)
        calculator_layout.addLayout(input_row)

        self.changeover_result_panel = QFrame()
        self.changeover_result_panel.setObjectName("panel")
        result_grid = QGridLayout(self.changeover_result_panel)
        result_grid.setContentsMargins(18, 16, 18, 16)
        result_grid.setHorizontalSpacing(28)
        result_grid.setVerticalSpacing(6)
        result_grid.addWidget(_section_label("RESULT"), 0, 0, 1, 3)
        self.changeover_time_heading = QLabel("CHANGEOVER TIME")
        result_grid.addWidget(self.changeover_time_heading, 1, 0)
        self.changeover_result_label = QLabel("-- h")
        self.changeover_result_label.setStyleSheet("font-size: 22pt; font-weight: 700;")
        result_grid.addWidget(self.changeover_result_label, 2, 0)
        self.changeover_minutes_label = QLabel("-- min")
        result_grid.addWidget(self.changeover_minutes_label, 3, 0)
        self.changeover_final_label = QLabel("Final Sulphur")
        self.changeover_steps_label = QLabel("Calculation Steps")
        self.changeover_timestep_label = QLabel("Time Step")
        self.changeover_temperature_rate_label = QLabel("Temperature Rate")
        self.changeover_final_value = QLabel("--")
        self.changeover_steps_value = QLabel("--")
        self.changeover_timestep_value = QLabel("--")
        self.changeover_temperature_advisory = QLabel("--")
        for row, (label, value) in enumerate(((self.changeover_final_label, self.changeover_final_value), (self.changeover_steps_label, self.changeover_steps_value), (self.changeover_timestep_label, self.changeover_timestep_value), (self.changeover_temperature_rate_label, self.changeover_temperature_advisory)), 1):
            result_grid.addWidget(label, row, 1)
            result_grid.addWidget(value, row, 2)
        result_grid.setColumnStretch(0, 2)
        result_grid.setColumnStretch(1, 2)
        result_grid.setColumnStretch(2, 1)
        calculator_layout.addWidget(self.changeover_result_panel)
        calculator_layout.addWidget(_section_label("SULPHUR PROGRESSION"))
        self.changeover_trace_table = QTableWidget(0, 2)
        self.changeover_trace_table.setHorizontalHeaderLabels(("Time (h)", "Sulphur (%)"))
        self.changeover_trace_table.verticalHeader().setVisible(False)
        self.changeover_trace_table.horizontalHeader().setStretchLastSection(True)
        self.changeover_trace_table.setMinimumHeight(190)
        calculator_layout.addWidget(self.changeover_trace_table)
        calculator_layout.addStretch()
        self.changeover_calculator_scroll.setWidget(calculator_content)
        calculator_root.addWidget(self.changeover_calculator_scroll)
        self.tabs.addTab(calculator_tab, "Changeover Calculator")

        projection_tab = QWidget()
        projection_tab_layout = QVBoxLayout(projection_tab)

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
        self.projection_table.verticalHeader().setDefaultSectionSize(32)
        self.projection_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        projection_layout.addWidget(self.projection_table)

        self.totals_label = QLabel("ULSFO Total: 0.00 MT   |   VLSFO Total: 0.00 MT   |   MDO Total: 0.00 MT")
        self.totals_label.setObjectName("fieldLabel")
        projection_layout.addWidget(self.totals_label)
        projection_tab_layout.addWidget(projection, 1)
        self.tabs.addTab(projection_tab, "Projection")

        layout.addStretch()

        self.refresh()

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self.vessel_label.setText("Vessel: Not configured")
            self._set_changeover_inputs_enabled(False)
            self.save_performance_button.setEnabled(False)
            self._clear_projection("No vessel configured.")
            self.status_label.setText("Configure a vessel before saving performance settings.")
            return

        self.vessel_label.setText(f"Vessel: {vessel.name}  |  IMO {vessel.imo}")
        self._set_changeover_inputs_enabled(True)
        self.save_performance_button.setEnabled(True)
        self._refresh_projection(vessel.id)
        self._refresh_fuel_state(vessel.id)
        self._refresh_changeovers(vessel.id)
        self._load_performance(vessel.id)
        self.status_label.setText("Performance settings loaded.")

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
        routes = {(route.origin_port, route.destination_port): route for route in self._voyage_service.list_routes()}
        issues: dict[int, str] = {}
        previous_port: str | None = None
        for row in timeline.rows:
            if previous_port is not None:
                route = routes.get((previous_port, row.event.port))
                if route is None or route.sea_distance_nm <= 0:
                    issues[row.event.id] = "Missing sea distance"
                elif row.interval_from_previous_hours is None:
                    issues[row.event.id] = "Upstream projection unavailable"
            previous_port = row.event.port
        for row in result.rows:
            if any(row.consumed_mt.get(fuel) is None for fuel in FUEL_TYPES):
                issues[row.event_id] = "Consumption incomplete"
        self.projection_table_model.set_rows(result.rows, issues)
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
        for widget in [
            *self._initial_fuel_inputs.values(),
            self.save_initial_fuel_button,
            self.change_machinery_input,
            self.change_from_input,
            self.change_to_input,
            self.change_planned_input,
            self.change_actual_enabled,
            self.change_actual_input,
            self.add_changeover_button,
            self.delete_changeover_button,
            self.apply_changeover_button,
        ]:
            widget.setEnabled(enabled)
        self.change_actual_input.setEnabled(enabled and self.change_actual_enabled.isChecked())
        self.apply_changeover_button.setEnabled(enabled and self._changeover_result is not None)

    def _refresh_fuel_state(self, vessel_id: int) -> None:
        state = self._voyage_service.load_initial_fuel_state(vessel_id)
        if state is None:
            for input_widget in self._initial_fuel_inputs.values():
                input_widget.setCurrentIndex(-1)
            return
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
                event.planned_at_utc.isoformat(timespec="minutes"),
                event.actual_at_utc.isoformat(timespec="minutes") if event.actual_at_utc else "",
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
            actual_at_utc=self.change_actual_input.dateTime().toPython() if self.change_actual_enabled.isChecked() else None,
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

    def _load_performance(self, vessel_id: int) -> None:
        config = self._voyage_service.load_energy_config(vessel_id)
        for key, spinbox in self._energy_inputs.items():
            spinbox.setValue(getattr(config, key))
        for key, input_widget in self._maneuvering_rate_inputs.items():
            value = getattr(config, key)
            input_widget.setText("" if value is None else str(value))
        self.generator_fuel_combo.setCurrentText(config.generator_fuel_type)
        self.boiler_fuel_combo.setCurrentText(config.boiler_fuel_type)
        me_sfoc_points = self._voyage_service.list_main_engine_sfoc_points(vessel_id)
        for index, (load_input, sfoc_input) in enumerate(self._main_engine_sfoc_inputs):
            point = me_sfoc_points[index] if index < len(me_sfoc_points) else None
            load_input.setValue(point.load_percent if point else 0.0)
            sfoc_input.setValue(point.sfoc_g_per_kwh if point else 0.0)
        sfoc_points = self._voyage_service.list_generator_sfoc_points(vessel_id)
        for index, (load_input, sfoc_input) in enumerate(self._sfoc_inputs):
            point = sfoc_points[index] if index < len(sfoc_points) else None
            load_input.setValue(point.load_percent if point else 0.0)
            sfoc_input.setValue(point.sfoc_g_per_kwh if point else 0.0)

    def _save_performance(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            return
        try:
            self._voyage_service.save_energy_config(
                VesselEnergyConfig(
                    vessel_id=vessel.id,
                    port_base_load_kw=self._energy_inputs["port_base_load_kw"].value(),
                    sea_base_load_kw=self._energy_inputs["sea_base_load_kw"].value(),
                    reefer_kw_per_unit=self._energy_inputs["reefer_kw_per_unit"].value(),
                    generator_rated_kw=self._energy_inputs["generator_rated_kw"].value(),
                    port_running_generators=self._energy_inputs["port_running_generators"].value(),
                    sea_running_generators=self._energy_inputs["sea_running_generators"].value(),
                    aux_boiler_mt_per_hour=self._energy_inputs["aux_boiler_mt_per_hour"].value(),
                    generator_fuel_type=self.generator_fuel_combo.currentText(),
                    boiler_fuel_type=self.boiler_fuel_combo.currentText(),
                    main_engine_slip_percent=self._energy_inputs["main_engine_slip_percent"].value(),
                    speed_rpm_factor=self._energy_inputs["speed_rpm_factor"].value(),
                    power_coefficient=self._energy_inputs["power_coefficient"].value(),
                    mcr_power_kw=self._energy_inputs["mcr_power_kw"].value(),
                    port_ambient_c=self._energy_inputs["port_ambient_c"].value(),
                    sea_ambient_c=self._energy_inputs["sea_ambient_c"].value(),
                    maneuvering_main_engine_mt_per_hour=_optional_float(self._maneuvering_rate_inputs["maneuvering_main_engine_mt_per_hour"]),
                    maneuvering_generators_mt_per_hour=_optional_float(self._maneuvering_rate_inputs["maneuvering_generators_mt_per_hour"]),
                    maneuvering_aux_boiler_mt_per_hour=_optional_float(self._maneuvering_rate_inputs["maneuvering_aux_boiler_mt_per_hour"]),
                )
            )
            me_sfoc_points = [
                MainEngineSfocPoint(vessel.id, load.value(), sfoc.value())
                for load, sfoc in self._main_engine_sfoc_inputs
                if load.value() > 0 or sfoc.value() > 0
            ]
            self._voyage_service.save_main_engine_sfoc_points(vessel.id, me_sfoc_points)
            sfoc_points = [
                GeneratorSfocPoint(vessel.id, load.value(), sfoc.value())
                for load, sfoc in self._sfoc_inputs
                if load.value() > 0 or sfoc.value() > 0
            ]
            self._voyage_service.save_generator_sfoc_points(vessel.id, sfoc_points)
        except Exception as exc:
            QMessageBox.warning(self, "Performance settings not saved", str(exc))
            return
        self._refresh_projection(vessel.id)
        self.status_label.setText("Performance settings saved.")

    def _calculate_changeover(self) -> None:
        try:
            result = calculate_fuel_changeover(
                self.changeover_calculator_inputs["flow"].value(), self.changeover_calculator_inputs["mass"].value(),
                self.changeover_calculator_inputs["from"].value(), self.changeover_calculator_inputs["to"].value(), self.changeover_calculator_inputs["target"].value(),
            )
        except FuelChangeoverCalculationError as error:
            QMessageBox.warning(self, "Changeover calculation", str(error)); return
        self._changeover_result = result
        self.apply_changeover_button.setEnabled(self._vessel_service.get_active_vessel() is not None)
        self.changeover_result_label.setText(f"{result.changeover_time_hours:.1f} h")
        self.changeover_minutes_label.setText(f"{result.changeover_time_hours * 60:.0f} min")
        self.changeover_final_value.setText(f"{result.final_sulfur_percent:.5f} %"); self.changeover_steps_value.setText(str(result.steps)); self.changeover_timestep_value.setText(f"{result.time_step_hours:.1f} h")
        self.changeover_trace_table.setRowCount(0)
        trace = result.trace if len(result.trace) <= 200 else (*result.trace[:100], *result.trace[-100:])
        for row, point in enumerate(trace):
            self.changeover_trace_table.insertRow(row); self.changeover_trace_table.setItem(row, 0, QTableWidgetItem(f"{point.time_hours:.1f}")); self.changeover_trace_table.setItem(row, 1, QTableWidgetItem(f"{point.sulfur_percent:.5f}"))
        try:
            from_temp, to_temp = float(self.changeover_from_temperature.text()), float(self.changeover_to_temperature.text())
            if result.changeover_time_hours == 0: self.changeover_temperature_advisory.setText("Not applicable")
            else:
                rate=abs(from_temp-to_temp)/(result.changeover_time_hours*60); self.changeover_temperature_advisory.setText(f"{rate:.3f} C/min" + ("  ⚠ exceeds 2 C/min" if rate > 2 else ""))
        except ValueError:
            self.changeover_temperature_advisory.setText("--")

    def _apply_changeover_calculation(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None or self._changeover_result is None:
            return
        dialog = ApplyChangeoverCalculationDialog(
            self._changeover_result,
            self.changeover_calculator_inputs["from"].value(),
            self.changeover_calculator_inputs["to"].value(),
            self.changeover_calculator_inputs["target"].value(),
            lambda machinery, effective_at_utc: self._planned_fuel_before(vessel.id, machinery, effective_at_utc),
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        event = FuelChangeoverEvent(
            id=None,
            vessel_id=vessel.id,
            machinery=values["machinery"],
            from_fuel_type=values["from_fuel_type"],
            to_fuel_type=values["to_fuel_type"],
            planned_at_utc=values["effective_at_utc"],
            actual_at_utc=None,
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
        self.status_label.setText("Fuel changeover saved at its effective completion time.")
        self.changeover_saved.emit()

    def _planned_fuel_before(self, vessel_id: int, machinery: str, effective_at_utc: datetime) -> str | None:
        state = self._voyage_service.load_initial_fuel_state(vessel_id)
        if state is None:
            return None
        fuel = state.fuel_for(machinery)
        cutoff = _as_utc(effective_at_utc)
        for event in self._voyage_service.list_fuel_changeovers(vessel_id):
            if event.machinery != machinery or _as_utc(event.effective_at_utc) >= cutoff:
                continue
            fuel = event.to_fuel_type
        return fuel

    def _reset_changeover(self) -> None:
        for widget in self.changeover_calculator_inputs.values(): widget.setValue(0)
        self._changeover_result = None
        self.apply_changeover_button.setEnabled(False)
        self.changeover_from_temperature.clear(); self.changeover_to_temperature.clear(); self.changeover_result_label.setText("-- h"); self.changeover_minutes_label.setText("-- min"); self.changeover_final_value.setText("--"); self.changeover_steps_value.setText("--"); self.changeover_timestep_value.setText("--"); self.changeover_temperature_advisory.setText("--"); self.changeover_trace_table.setRowCount(0)


class ApplyChangeoverCalculationDialog(QDialog):
    def __init__(self, result, from_sulfur_percent: float, to_sulfur_percent: float, target_sulfur_percent: float, planned_fuel_before, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Apply Changeover Calculation")
        self._result = result
        self._planned_fuel_before = planned_fuel_before

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        layout.addLayout(grid)

        self.machinery_input = QComboBox()
        self.machinery_input.addItem("Select machinery...", None)
        for machinery, label in (("MAIN_ENGINE", "Main Engine"), ("GENERATORS", "Generators"), ("AUX_BOILER", "Auxiliary Boiler")):
            self.machinery_input.addItem(label, machinery)
        self.from_fuel_input = QComboBox()
        self.from_fuel_input.addItem("Select FROM fuel...", None)
        self.to_fuel_input = QComboBox()
        self.to_fuel_input.addItem("Select TO fuel...", None)
        for fuel_type in FUEL_TYPES:
            self.from_fuel_input.addItem(fuel_type, fuel_type)
            self.to_fuel_input.addItem(fuel_type, fuel_type)

        self.duration_value = QLabel(f"{result.changeover_time_hours:.1f} h / {result.changeover_time_hours * 60:.0f} min")
        self.target_sulfur_value = QLabel(f"{target_sulfur_percent:.5f} %")
        self.from_sulfur_value = QLabel(f"{from_sulfur_percent:.5f} %")
        self.to_sulfur_value = QLabel(f"{to_sulfur_percent:.5f} %")
        self.effective_input = QDateTimeEdit()
        self.effective_input.setTimeZone(QTimeZone.utc())
        self.effective_input.setDateTime(QDateTime.currentDateTimeUtc())
        self.effective_input.setCalendarPopup(True)
        self.effective_input.setDisplayFormat("dd MMM yyyy HH:mm 'UTC'")
        self.recommended_start_value = QLabel()
        self.remarks_input = QLineEdit()
        self.remarks_input.setPlaceholderText("Optional; not persisted with the current event schema")

        for row, (label, widget) in enumerate((
            ("Machinery", self.machinery_input),
            ("FROM Fuel", self.from_fuel_input),
            ("TO Fuel", self.to_fuel_input),
            ("Calculated Duration", self.duration_value),
            ("Target Sulphur", self.target_sulfur_value),
            ("FROM Sulphur", self.from_sulfur_value),
            ("TO Sulphur", self.to_sulfur_value),
            ("Effective / Completion Time UTC", self.effective_input),
            ("Recommended Start Time UTC", self.recommended_start_value),
            ("Remarks", self.remarks_input),
        )):
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(widget, row, 1)
        self.effective_input.dateTimeChanged.connect(self._update_recommended_start)
        self._update_recommended_start()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _effective_at_utc(self) -> datetime:
        utc_value = self.effective_input.dateTime().toUTC()
        return datetime.fromtimestamp(utc_value.toSecsSinceEpoch(), timezone.utc)

    def _update_recommended_start(self) -> None:
        start = self._effective_at_utc() - timedelta(hours=self._result.changeover_time_hours)
        self.recommended_start_value.setText(start.strftime("%d %b %Y %H:%M UTC"))

    def values(self) -> dict[str, object]:
        effective_at_utc = self._effective_at_utc()
        return {
            "machinery": self.machinery_input.currentData(),
            "from_fuel_type": self.from_fuel_input.currentData(),
            "to_fuel_type": self.to_fuel_input.currentData(),
            "effective_at_utc": effective_at_utc,
            "recommended_start_utc": effective_at_utc - timedelta(hours=self._result.changeover_time_hours),
            "remarks": self.remarks_input.text().strip(),
        }

    def _validate_and_accept(self) -> None:
        machinery = self.machinery_input.currentData()
        if machinery is None:
            QMessageBox.warning(self, "Apply Changeover", "Select machinery before applying the changeover.")
            return
        if self.from_fuel_input.currentData() is None:
            QMessageBox.warning(self, "Apply Changeover", "Select a FROM fuel explicitly.")
            return
        if self.to_fuel_input.currentData() is None:
            QMessageBox.warning(self, "Apply Changeover", "Select a TO fuel explicitly.")
            return
        planned_fuel = self._planned_fuel_before(machinery, self._effective_at_utc())
        if planned_fuel is not None and planned_fuel != self.from_fuel_input.currentData():
            QMessageBox.warning(self, "Apply Changeover", f"Selected FROM fuel ({self.from_fuel_input.currentData()}) does not match the planned {planned_fuel} fuel for this machinery before the effective time.")
            return
        self.accept()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _format_mt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f} MT"


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


def _spinbox(suffix: str, minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
    spinbox = QDoubleSpinBox()
    spinbox.setDecimals(2)
    spinbox.setRange(minimum, maximum)
    spinbox.setSingleStep(step)
    spinbox.setSuffix(suffix)
    return spinbox


def _optional_float(input_widget: QLineEdit) -> float | None:
    text = input_widget.text().strip()
    return None if not text else float(text)


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def _help_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("mutedText")
    label.setWordWrap(True)
    return label
    QScrollArea,
