from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QDateTime, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES, OPERATING_MODES
from fuel_consumption_calculator.domain.voyage import FuelChangeoverEvent, GeneratorSfocPoint, MachineryFuelState, MACHINERY_TYPES, MainEngineSfocPoint, VesselEnergyConfig
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
        self._energy_inputs: dict[str, QDoubleSpinBox] = {}
        self._main_engine_sfoc_inputs: list[tuple[QDoubleSpinBox, QDoubleSpinBox]] = []
        self._sfoc_inputs: list[tuple[QDoubleSpinBox, QDoubleSpinBox]] = []

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
        for column, header in enumerate(("ME Load %", "ME SFOC g/kWh")):
            engine_grid.addWidget(QLabel(header), 4, column)
        for row in range(17):
            load_input = _spinbox(" %", 0, 200, 5)
            sfoc_input = _spinbox(" g/kWh", 0, 9999, 1)
            engine_grid.addWidget(load_input, row + 5, 0)
            engine_grid.addWidget(sfoc_input, row + 5, 1)
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
        fallback_layout.addWidget(_section_label("Fixed-Rate Fallback"))
        fallback_layout.addWidget(_help_label("Used only when detailed vessel-performance data is unavailable."))
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
        self.projection_table.verticalHeader().setDefaultSectionSize(32)
        self.projection_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
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
            self.save_performance_button.setEnabled(False)
            self._set_rates_to_zero()
            self._clear_projection("No vessel configured.")
            self.status_label.setText("Configure a vessel before saving consumption rates.")
            return

        self.vessel_label.setText(f"Vessel: {vessel.name}  |  IMO {vessel.imo}")
        self.save_button.setEnabled(True)
        self._set_inputs_enabled(True)
        self._set_changeover_inputs_enabled(True)
        self.save_performance_button.setEnabled(True)
        profile = self._consumption_service.load_profile(vessel.id)
        for key, spinbox in self._rate_inputs.items():
            spinbox.setValue(profile.rate_for(*key))
        self._refresh_projection(vessel.id)
        self._refresh_fuel_state(vessel.id)
        self._refresh_changeovers(vessel.id)
        self._load_performance(vessel.id)
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
        ]:
            widget.setEnabled(enabled)
        self.change_actual_input.setEnabled(enabled and self.change_actual_enabled.isChecked())

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


def _spinbox(suffix: str, minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
    spinbox = QDoubleSpinBox()
    spinbox.setDecimals(2)
    spinbox.setRange(minimum, maximum)
    spinbox.setSingleStep(step)
    spinbox.setSuffix(suffix)
    return spinbox


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
