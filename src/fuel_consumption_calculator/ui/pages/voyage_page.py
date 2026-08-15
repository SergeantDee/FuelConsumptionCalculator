from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QDateTime, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.voyage import CalculatedVoyageLeg, SpeedConsumptionPoint
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
        self._speed_inputs: list[tuple[QDoubleSpinBox, dict[str, QDoubleSpinBox]]] = []

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
        self.legs_table.horizontalHeader().setStretchLastSection(True)
        self.legs_table.selectionModel().selectionChanged.connect(self._selection_changed)
        layout.addWidget(self.legs_table, 1)

        editor = QFrame()
        editor.setObjectName("panel")
        grid = QGridLayout(editor)
        grid.setContentsMargins(18, 16, 18, 16)
        labels = [
            "Dep Pilot Dist NM",
            "Dep Pilot Hours",
            "Sea Distance NM",
            "Arr Pilot Dist NM",
            "Arr Pilot Hours",
        ]
        self.dep_pilot_dist = _spinbox(" NM", 0, 99999, 1)
        self.dep_pilot_hours = _spinbox(" h", 0, 999, 0.25)
        self.sea_distance = _spinbox(" NM", 0, 99999, 10)
        self.arr_pilot_dist = _spinbox(" NM", 0, 99999, 1)
        self.arr_pilot_hours = _spinbox(" h", 0, 999, 0.25)
        for column, (label, widget) in enumerate(zip(labels, [self.dep_pilot_dist, self.dep_pilot_hours, self.sea_distance, self.arr_pilot_dist, self.arr_pilot_hours])):
            grid.addWidget(QLabel(label), 0, column)
            grid.addWidget(widget, 1, column)

        actuals = [
            ("Actual Berth Dep", "actual_berth_departure"),
            ("Actual Pilot Off", "actual_pilot_off"),
            ("Actual Pilot On", "actual_pilot_on"),
            ("Actual Berth Arr", "actual_berth_arrival"),
        ]
        self._actual_enabled: dict[str, QCheckBox] = {}
        self._actual_inputs: dict[str, QDateTimeEdit] = {}
        for column, (label, key) in enumerate(actuals):
            checkbox = QCheckBox(label)
            dt_input = QDateTimeEdit()
            dt_input.setDisplayFormat("dd MMM yyyy HH:mm")
            dt_input.setCalendarPopup(True)
            grid.addWidget(checkbox, 2, column)
            grid.addWidget(dt_input, 3, column)
            self._actual_enabled[key] = checkbox
            self._actual_inputs[key] = dt_input

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
        grid.addLayout(actions, 4, 0, 1, 5)
        layout.addWidget(editor)

        speed_panel = QFrame()
        speed_panel.setObjectName("panel")
        speed_grid = QGridLayout(speed_panel)
        speed_grid.setContentsMargins(18, 16, 18, 16)
        speed_grid.addWidget(QLabel("SPEED-CONSUMPTION POINTS (linear interpolation, no extrapolation)"), 0, 0, 1, 4)
        for column, header in enumerate(("Speed kn", "ULSFO MT/day", "VLSFO MT/day", "MDO MT/day")):
            speed_grid.addWidget(QLabel(header), 1, column)
        for row in range(3):
            speed_input = _spinbox(" kn", 0, 50, 1)
            rate_inputs = {fuel_type: _spinbox(" MT/day", 0, 9999, 1) for fuel_type in FUEL_TYPES}
            speed_grid.addWidget(speed_input, row + 2, 0)
            for column, fuel_type in enumerate(FUEL_TYPES, start=1):
                speed_grid.addWidget(rate_inputs[fuel_type], row + 2, column)
            self._speed_inputs.append((speed_input, rate_inputs))
        self.save_speed_button = QPushButton("Save Speed Table")
        self.save_speed_button.clicked.connect(self._save_speed_points)
        speed_grid.addWidget(self.save_speed_button, 5, 0, 1, 4)
        layout.addWidget(speed_panel)

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
        self._load_speed_points(vessel.id)
        self.status_label.setText("; ".join(plan.warnings[:2]) if plan.warnings else f"Loaded {len(plan.legs)} voyage legs.")
        if plan.legs and not self.legs_table.selectionModel().selectedRows():
            self.legs_table.selectRow(0)
        else:
            self._selection_changed()

    def _selection_changed(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        self._loading = True
        override = row.leg.override
        self.dep_pilot_dist.setValue(_effective(override.departure_pilot_distance_nm if override else None, row.leg.route.departure_pilot_distance_nm))
        self.dep_pilot_hours.setValue(_effective(override.departure_pilotage_hours if override else None, row.leg.route.departure_pilotage_hours))
        self.sea_distance.setValue(_effective(override.sea_distance_nm if override else None, row.leg.route.sea_distance_nm))
        self.arr_pilot_dist.setValue(_effective(override.arrival_pilot_distance_nm if override else None, row.leg.route.arrival_pilot_distance_nm))
        self.arr_pilot_hours.setValue(_effective(override.arrival_pilotage_hours if override else None, row.leg.route.arrival_pilotage_hours))
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
            for speed_input, rate_inputs in self._speed_inputs:
                if speed_input.value() <= 0:
                    continue
                points.append(
                    self._voyage_service.build_speed_point(
                        vessel.id,
                        speed_input.value(),
                        {fuel_type: rate_inputs[fuel_type].value() for fuel_type in FUEL_TYPES},
                    )
                )
            self._voyage_service.save_speed_points(vessel.id, points)
        except Exception as exc:
            QMessageBox.warning(self, "Speed table not saved", str(exc))
            return
        self.refresh()
        self.status_label.setText("Speed-consumption table saved.")

    def _load_speed_points(self, vessel_id: int) -> None:
        self._loading = True
        points = self._voyage_service.list_speed_points(vessel_id)
        for index, (speed_input, rate_inputs) in enumerate(self._speed_inputs):
            point = points[index] if index < len(points) else None
            speed_input.setValue(point.speed_knots if point else 0.0)
            for fuel_type in FUEL_TYPES:
                rate_inputs[fuel_type].setValue(point.rate_for(fuel_type) if point else 0.0)
        self._loading = False

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
            self.save_speed_button,
        ]:
            widget.setEnabled(enabled)


def _spinbox(suffix: str, minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
    spinbox = QDoubleSpinBox()
    spinbox.setDecimals(2)
    spinbox.setRange(minimum, maximum)
    spinbox.setSingleStep(step)
    spinbox.setSuffix(suffix)
    return spinbox


def _fmt_dt(value: datetime) -> str:
    return value.strftime("%d %b %Y %H:%M")


def _effective(value: float | None, default: float) -> float:
    return float(default if value is None else value)
