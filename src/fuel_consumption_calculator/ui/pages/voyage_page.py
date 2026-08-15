from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QDateTime, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QTableView,
    QVBoxLayout,
    QWidget,
)

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.voyage import CalculatedVoyageLeg, GeneratorSfocPoint, SpeedConsumptionPoint, VesselEnergyConfig
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.services.voyage_service import VoyageService
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader


class VoyageLegTableModel(QAbstractTableModel):
    HEADERS = (
        "From",
        "To",
        "Berth Dep",
        "Pilot Off",
        "Sea NM",
        "Sea Time",
        "Req Speed",
        "Pilot On",
        "Berth Arr",
        "Status",
    )

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[CalculatedVoyageLeg] = []

    def rowCount(self, parent=None) -> int:
        return len(self._rows)

    def columnCount(self, parent=None) -> int:
        return len(self.HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        row = self._rows[index.row()]
        values = (
            row.leg.origin_port,
            row.leg.destination_port,
            _fmt_dt(row.effective_berth_departure),
            _fmt_dt(row.pilot_off),
            f"{row.sea_distance_nm:.1f}",
            f"{row.sea_hours:.2f} h",
            f"{row.required_speed_knots:.2f} kn" if row.required_speed_knots is not None else "",
            _fmt_dt(row.pilot_on),
            _fmt_dt(row.effective_berth_arrival),
            "WARN" if row.warnings else row.leg.status,
        )
        return values[index.column()]

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return self.HEADERS[section] if orientation == Qt.Orientation.Horizontal else str(section + 1)

    def set_rows(self, rows: list[CalculatedVoyageLeg]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row_at(self, row: int) -> CalculatedVoyageLeg | None:
        if not 0 <= row < len(self._rows):
            return None
        return self._rows[row]


class VoyagePage(QWidget):
    def __init__(
        self,
        vessel_service: VesselService,
        schedule_service: ScheduleService,
        consumption_service: ConsumptionService,
        voyage_service: VoyageService,
    ) -> None:
        super().__init__()
        self._vessel_service = vessel_service
        self._schedule_service = schedule_service
        self._consumption_service = consumption_service
        self._voyage_service = voyage_service
        self._loading = False
        self._speed_inputs: list[tuple[QDoubleSpinBox, QDoubleSpinBox, dict[str, QDoubleSpinBox]]] = []
        self._sfoc_inputs: list[tuple[QDoubleSpinBox, QDoubleSpinBox]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)
        layout.addWidget(PageHeader("Voyage Planner", "Plan berth-pilot-sea-pilot-berth voyage legs."))

        self.vessel_label = QLabel("Vessel: Not configured")
        self.vessel_label.setObjectName("fieldLabel")
        layout.addWidget(self.vessel_label)

        self.legs_model = VoyageLegTableModel()
        self.legs_table = QTableView()
        self.legs_table.setModel(self.legs_model)
        self.legs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.legs_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.legs_table.verticalHeader().setDefaultSectionSize(32)
        self.legs_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.legs_table.horizontalHeader().setStretchLastSection(True)
        self.legs_table.setMinimumHeight(180)
        self.legs_table.selectionModel().selectionChanged.connect(self._selection_changed)
        layout.addWidget(self.legs_table, 1)

        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        detail_container = QWidget()
        detail_layout = QVBoxLayout(detail_container)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(12)

        schedule_panel = _section("Schedule")
        schedule_grid = QGridLayout(schedule_panel)
        schedule_grid.setContentsMargins(18, 16, 18, 16)
        _add_section_title(schedule_grid, "Schedule")
        self.from_port_label = QLabel("-")
        self.to_port_label = QLabel("-")
        self.scheduled_departure_label = QLabel("-")
        self.scheduled_arrival_label = QLabel("-")
        _add_value(schedule_grid, 1, 0, "From Port", self.from_port_label)
        _add_value(schedule_grid, 1, 1, "To Port", self.to_port_label)
        _add_value(schedule_grid, 2, 0, "Scheduled Berth Departure", self.scheduled_departure_label)
        _add_value(schedule_grid, 2, 1, "Scheduled Berth Arrival", self.scheduled_arrival_label)
        detail_layout.addWidget(schedule_panel)

        departure_panel = _section("Departure / Pilotage")
        departure_grid = QGridLayout(departure_panel)
        departure_grid.setContentsMargins(18, 16, 18, 16)
        _add_section_title(departure_grid, "Departure / Pilotage")
        self.dep_pilot_dist = _spinbox(" NM", 0, 99999, 1)
        self.dep_pilot_hours = _spinbox(" h", 0, 999, 0.25)
        self.calculated_pilot_off_label = QLabel("-")
        self._actual_enabled: dict[str, QCheckBox] = {}
        self._actual_inputs: dict[str, QDateTimeEdit] = {}
        _add_control(departure_grid, 1, 0, "Departure Pilot Distance NM", self.dep_pilot_dist)
        _add_control(departure_grid, 1, 1, "Departure Pilot Hours", self.dep_pilot_hours)
        _add_value(departure_grid, 2, 0, "Calculated Pilot Off", self.calculated_pilot_off_label)
        self._add_actual_control(departure_grid, 2, 1, "Actual Berth Departure", "actual_berth_departure")
        self._add_actual_control(departure_grid, 3, 0, "Actual Pilot Off", "actual_pilot_off")
        detail_layout.addWidget(departure_panel)

        sea_panel = _section("Sea Passage")
        sea_grid = QGridLayout(sea_panel)
        sea_grid.setContentsMargins(18, 16, 18, 16)
        _add_section_title(sea_grid, "Sea Passage")
        self.sea_distance = _spinbox(" NM", 0, 99999, 10)
        self.sea_time_label = QLabel("-")
        self.required_speed_label = QLabel("-")
        self.predicted_me_load_label = QLabel("-")
        self.egb_available_label = QLabel("-")
        self.departure_reefers = _spinbox("", 0, 999999, 1)
        self.use_egb_check = QCheckBox("Use EGB")
        _add_control(sea_grid, 1, 0, "Sea Distance NM", self.sea_distance)
        _add_value(sea_grid, 1, 1, "Sea Time", self.sea_time_label)
        _add_value(sea_grid, 2, 0, "Required Speed", self.required_speed_label)
        _add_value(sea_grid, 2, 1, "Predicted ME Load %", self.predicted_me_load_label)
        _add_control(sea_grid, 3, 0, "Departure Reefers", self.departure_reefers)
        _add_value(sea_grid, 3, 1, "EGB Available", self.egb_available_label)
        sea_grid.addWidget(self.use_egb_check, 4, 0, 1, 2)
        detail_layout.addWidget(sea_panel)

        arrival_panel = _section("Arrival / Pilotage")
        arrival_grid = QGridLayout(arrival_panel)
        arrival_grid.setContentsMargins(18, 16, 18, 16)
        _add_section_title(arrival_grid, "Arrival / Pilotage")
        self.arr_pilot_dist = _spinbox(" NM", 0, 99999, 1)
        self.arr_pilot_hours = _spinbox(" h", 0, 999, 0.25)
        self.calculated_pilot_on_label = QLabel("-")
        self.port_reefers = _spinbox("", 0, 999999, 1)
        _add_value(arrival_grid, 1, 0, "Calculated Pilot On", self.calculated_pilot_on_label)
        self._add_actual_control(arrival_grid, 1, 1, "Actual Pilot On", "actual_pilot_on")
        _add_control(arrival_grid, 2, 0, "Arrival Pilot Distance NM", self.arr_pilot_dist)
        _add_control(arrival_grid, 2, 1, "Arrival Pilot Hours", self.arr_pilot_hours)
        self._add_actual_control(arrival_grid, 3, 0, "Actual Berth Arrival", "actual_berth_arrival")
        _add_control(arrival_grid, 3, 1, "Port Stay Reefers", self.port_reefers)
        detail_layout.addWidget(arrival_panel)

        actions_panel = _section("Route Actions")
        actions_grid = QGridLayout(actions_panel)
        actions_grid.setContentsMargins(18, 16, 18, 16)
        _add_section_title(actions_grid, "Route Actions")
        self.save_library_check = QCheckBox("Also save route library")
        self.save_leg_button = QPushButton("Save / Apply Leg Values")
        self.save_leg_button.setObjectName("primaryButton")
        self.save_leg_button.clicked.connect(self._save_leg)
        self.reset_leg_button = QPushButton("Reset Selected Leg to Library")
        self.reset_leg_button.clicked.connect(self._reset_leg)
        actions = QHBoxLayout()
        actions.addWidget(self.save_library_check)
        actions.addWidget(self.save_leg_button)
        actions.addWidget(self.reset_leg_button)
        actions.addStretch()
        actions_grid.addLayout(actions, 1, 0)
        detail_layout.addWidget(actions_panel)

        clock_panel = _section("Vessel Clock")
        clock_grid = QGridLayout(clock_panel)
        clock_grid.setContentsMargins(18, 16, 18, 16)
        _add_section_title(clock_grid, "Vessel Clock")
        self.clock_offset_label = QLabel("UTC +00:00")
        _add_value(clock_grid, 1, 0, "Current Vessel UTC Offset", self.clock_offset_label)
        clock_grid.addWidget(QLabel("Clock adjustment controls/history are managed by the vessel-clock timeline."), 2, 0)
        detail_layout.addWidget(clock_panel)
        detail_layout.addStretch()
        detail_scroll.setWidget(detail_container)
        layout.addWidget(detail_scroll, 2)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("mutedText")
        layout.addWidget(self.status_label)
        self.refresh()

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self.vessel_label.setText("Vessel: Not configured")
            self.legs_model.set_rows([])
            self._set_enabled(False)
            return
        self._set_enabled(True)
        self.vessel_label.setText(f"Vessel: {vessel.name}  |  IMO {vessel.imo}")
        events = self._schedule_service.list_events(vessel.id)
        profile = self._consumption_service.load_profile(vessel.id)
        plan = self._voyage_service.calculate_plan(vessel.id, events, profile)
        self.legs_model.set_rows(plan.legs)
        self._resize_leg_columns()
        self.status_label.setText("; ".join(plan.warnings[:2]) if plan.warnings else f"Loaded {len(plan.legs)} voyage legs.")
        if plan.legs and not self.legs_table.selectionModel().selectedRows():
            self.legs_table.selectRow(0)
        else:
            self._selection_changed()

    def _resize_leg_columns(self) -> None:
        for index, width in enumerate((120, 150, 135, 135, 85, 90, 95, 135, 135, 85)):
            self.legs_table.setColumnWidth(index, width)

    def _selection_changed(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        self._loading = True
        override = row.leg.override
        self.from_port_label.setText(row.leg.origin_port)
        self.to_port_label.setText(row.leg.destination_port)
        self.scheduled_departure_label.setText(_fmt_dt(row.leg.scheduled_berth_departure))
        self.scheduled_arrival_label.setText(_fmt_dt(row.leg.scheduled_berth_arrival))
        self.calculated_pilot_off_label.setText(_fmt_dt(row.pilot_off))
        self.calculated_pilot_on_label.setText(_fmt_dt(row.pilot_on))
        self.sea_time_label.setText(f"{row.sea_hours:.2f} h")
        self.required_speed_label.setText(f"{row.required_speed_knots:.2f} kn" if row.required_speed_knots is not None else "-")
        self.predicted_me_load_label.setText(f"{row.predicted_me_load_percent:.2f} %" if row.predicted_me_load_percent is not None else "-")
        self.egb_available_label.setText("Yes" if row.egb_available else "No")
        self.dep_pilot_dist.setValue(_effective(override.departure_pilot_distance_nm if override else None, row.leg.route.departure_pilot_distance_nm))
        self.dep_pilot_hours.setValue(_effective(override.departure_pilotage_hours if override else None, row.leg.route.departure_pilotage_hours))
        self.sea_distance.setValue(_effective(override.sea_distance_nm if override else None, row.leg.route.sea_distance_nm))
        self.arr_pilot_dist.setValue(_effective(override.arrival_pilot_distance_nm if override else None, row.leg.route.arrival_pilot_distance_nm))
        self.arr_pilot_hours.setValue(_effective(override.arrival_pilotage_hours if override else None, row.leg.route.arrival_pilotage_hours))
        self.port_reefers.setValue(override.port_reefers if override and override.port_reefers is not None else 0.0)
        self.departure_reefers.setValue(override.departure_reefers if override and override.departure_reefers is not None else 0.0)
        self.use_egb_check.setChecked(bool(override.use_egb) if override else False)
        self.use_egb_check.setEnabled(row.egb_available)
        for key, input_widget in self._actual_inputs.items():
            value = getattr(override, key) if override else None
            fallback = {
                "actual_berth_departure": row.effective_berth_departure,
                "actual_pilot_off": row.pilot_off,
                "actual_pilot_on": row.pilot_on,
                "actual_berth_arrival": row.effective_berth_arrival,
            }[key]
            self._actual_enabled[key].setChecked(value is not None)
            input_widget.setDateTime(QDateTime(fallback if value is None else value))
        self._loading = False

    def _add_actual_control(self, grid: QGridLayout, row: int, column: int, label: str, key: str) -> None:
        checkbox = QCheckBox(label)
        dt_input = QDateTimeEdit()
        dt_input.setDisplayFormat("dd MMM yyyy HH:mm")
        dt_input.setCalendarPopup(True)
        grid.addWidget(checkbox, row * 2 - 1, column)
        grid.addWidget(dt_input, row * 2, column)
        self._actual_enabled[key] = checkbox
        self._actual_inputs[key] = dt_input

    def _save_leg(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        try:
            self._voyage_service.save_leg_values(
                row.leg,
                departure_pilot_distance_nm=self.dep_pilot_dist.value(),
                departure_pilotage_hours=self.dep_pilot_hours.value(),
                sea_distance_nm=self.sea_distance.value(),
                arrival_pilot_distance_nm=self.arr_pilot_dist.value(),
                arrival_pilotage_hours=self.arr_pilot_hours.value(),
                actual_berth_departure=self._actual_value("actual_berth_departure"),
                actual_pilot_off=self._actual_value("actual_pilot_off"),
                actual_pilot_on=self._actual_value("actual_pilot_on"),
                actual_berth_arrival=self._actual_value("actual_berth_arrival"),
                port_reefers=self.port_reefers.value() if hasattr(self, "port_reefers") else 0.0,
                departure_reefers=self.departure_reefers.value() if hasattr(self, "departure_reefers") else 0.0,
                use_egb=self.use_egb_check.isChecked() if hasattr(self, "use_egb_check") else False,
                save_library=self.save_library_check.isChecked(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Voyage leg not saved", str(exc))
            return
        self.refresh()
        self.status_label.setText("Voyage leg saved and projections refreshed.")

    def _reset_leg(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        self._voyage_service.reset_leg_to_library(row.leg)
        self.refresh()
        self.status_label.setText("Voyage leg reset to route library values.")

    def _save_speed_points(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            return
        points: list[SpeedConsumptionPoint] = []
        try:
            for speed_input, me_load_input, rate_inputs in self._speed_inputs:
                if speed_input.value() <= 0:
                    continue
                points.append(
                    self._voyage_service.build_speed_point(
                        vessel.id,
                        speed_input.value(),
                        {fuel_type: rate_inputs[fuel_type].value() for fuel_type in FUEL_TYPES},
                        me_load_input.value(),
                    )
                )
            self._voyage_service.save_speed_points(vessel.id, points)
            sfoc_points = [
                GeneratorSfocPoint(vessel.id, load.value(), sfoc.value())
                for load, sfoc in self._sfoc_inputs
                if load.value() > 0 or sfoc.value() > 0
            ]
            self._voyage_service.save_generator_sfoc_points(vessel.id, sfoc_points)
        except Exception as exc:
            QMessageBox.warning(self, "Speed table not saved", str(exc))
            return
        self.refresh()
        self.status_label.setText("Speed-consumption table saved.")

    def _load_speed_points(self, vessel_id: int) -> None:
        self._loading = True
        points = self._voyage_service.list_speed_points(vessel_id)
        for index, (speed_input, me_load_input, rate_inputs) in enumerate(self._speed_inputs):
            point = points[index] if index < len(points) else None
            speed_input.setValue(point.speed_knots if point else 0.0)
            me_load_input.setValue(point.main_engine_load_percent if point and point.main_engine_load_percent is not None else 0.0)
            for fuel_type in FUEL_TYPES:
                rate_inputs[fuel_type].setValue(point.rate_for(fuel_type) if point else 0.0)
        sfoc_points = self._voyage_service.list_generator_sfoc_points(vessel_id)
        for index, (load_input, sfoc_input) in enumerate(self._sfoc_inputs):
            point = sfoc_points[index] if index < len(sfoc_points) else None
            load_input.setValue(point.load_percent if point else 0.0)
            sfoc_input.setValue(point.sfoc_g_per_kwh if point else 0.0)
        self._loading = False

    def _load_energy_config(self, vessel_id: int) -> None:
        config = self._voyage_service.load_energy_config(vessel_id)
        for key, spinbox in self._energy_inputs.items():
            spinbox.setValue(getattr(config, key))
        self.generator_fuel_combo.setCurrentText(config.generator_fuel_type)
        self.boiler_fuel_combo.setCurrentText(config.boiler_fuel_type)

    def _save_energy_config(self) -> None:
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
                )
            )
        except Exception as exc:
            QMessageBox.warning(self, "Energy config not saved", str(exc))
            return
        self.refresh()
        self.status_label.setText("Energy configuration saved.")

    def _selected_row(self) -> CalculatedVoyageLeg | None:
        selected = self.legs_table.selectionModel().selectedRows() if self.legs_table.selectionModel() else []
        if not selected:
            return None
        return self.legs_model.row_at(selected[0].row())

    def _actual_value(self, key: str) -> datetime | None:
        if not self._actual_enabled[key].isChecked():
            return None
        return self._actual_inputs[key].dateTime().toPython()

    def _set_enabled(self, enabled: bool) -> None:
        for widget in [
            self.legs_table,
            self.dep_pilot_dist,
            self.dep_pilot_hours,
            self.sea_distance,
            self.arr_pilot_dist,
            self.arr_pilot_hours,
            self.save_leg_button,
            self.reset_leg_button,
        ]:
            widget.setEnabled(enabled)


def _spinbox(suffix: str, minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
    spinbox = QDoubleSpinBox()
    spinbox.setDecimals(2)
    spinbox.setRange(minimum, maximum)
    spinbox.setSingleStep(step)
    spinbox.setSuffix(suffix)
    return spinbox


def _section(title: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName("panel")
    frame.setToolTip(title)
    return frame


def _add_control(grid: QGridLayout, row: int, column: int, label_text: str, widget: QWidget) -> None:
    label = QLabel(label_text)
    label.setObjectName("fieldLabel")
    grid.addWidget(label, row * 2 - 1, column)
    grid.addWidget(widget, row * 2, column)


def _add_value(grid: QGridLayout, row: int, column: int, label_text: str, value_label: QLabel) -> None:
    label = QLabel(label_text)
    label.setObjectName("fieldLabel")
    value_label.setObjectName("mutedText")
    grid.addWidget(label, row * 2 - 1, column)
    grid.addWidget(value_label, row * 2, column)


def _add_section_title(grid: QGridLayout, title: str) -> None:
    label = QLabel(title)
    label.setObjectName("sectionTitle")
    grid.addWidget(label, 0, 0, 1, 2)


def _fmt_dt(value: datetime) -> str:
    return value.strftime("%d %b %Y %H:%M")


def _effective(value: float | None, default: float) -> float:
    return float(default if value is None else value)
