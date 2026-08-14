from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
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

from fuel_consumption_calculator.calculations.rob_projection_engine import EventROBProjection
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.rob_service import ROBService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader


class ROBProjectionTableModel(QAbstractTableModel):
    HEADERS = (
        "Port",
        "Sea Duration",
        "Port Duration",
        "ULSFO Consumed",
        "VLSFO Consumed",
        "MDO Consumed",
        "ULSFO ROB",
        "VLSFO ROB",
        "MDO ROB",
    )

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[EventROBProjection] = []

    def rowCount(self, parent=None) -> int:
        return len(self._rows)

    def columnCount(self, parent=None) -> int:
        return len(self.HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        values = (
            row.port,
            _format_duration(row.sea_hours),
            _format_duration(row.port_hours),
            _format_mt(row.consumed_mt["ULSFO"]),
            _format_mt(row.consumed_mt["VLSFO"]),
            _format_mt(row.consumed_mt["MDO"]),
            _format_mt(row.projected_rob_mt["ULSFO"]),
            _format_mt(row.projected_rob_mt["VLSFO"]),
            _format_mt(row.projected_rob_mt["MDO"]),
        )
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and index.column() >= 6:
            rob_values = (
                row.projected_rob_mt["ULSFO"],
                row.projected_rob_mt["VLSFO"],
                row.projected_rob_mt["MDO"],
            )
            if rob_values[index.column() - 6] < 0:
                return QColor("#ff9b9b")
        return None

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return str(section + 1)

    def set_rows(self, rows: list[EventROBProjection]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()


class RobPage(QWidget):
    def __init__(
        self,
        vessel_service: VesselService,
        rob_service: ROBService,
        schedule_service: ScheduleService,
        consumption_service: ConsumptionService,
    ) -> None:
        super().__init__()
        self._vessel_service = vessel_service
        self._rob_service = rob_service
        self._schedule_service = schedule_service
        self._consumption_service = consumption_service
        self._rob_inputs: dict[str, QDoubleSpinBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)
        layout.addWidget(PageHeader("ROB Planner", "Project remaining fuel after scheduled consumption."))

        self.vessel_label = QLabel("Vessel: Not configured")
        self.vessel_label.setObjectName("fieldLabel")
        layout.addWidget(self.vessel_label)

        editor = QFrame()
        editor.setObjectName("panel")
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(18, 16, 18, 16)
        editor_layout.setSpacing(10)
        title = QLabel("STARTING ROB FOR SCHEDULE PROJECTION")
        title.setObjectName("fieldLabel")
        editor_layout.addWidget(title)
        note = QLabel("Starting ROB is the fuel onboard immediately before the first modeled schedule item begins.")
        note.setObjectName("mutedText")
        editor_layout.addWidget(note)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        for column, fuel_type in enumerate(FUEL_TYPES):
            label = QLabel(fuel_type)
            label.setObjectName("fieldLabel")
            grid.addWidget(label, 0, column)
            spinbox = QDoubleSpinBox()
            spinbox.setDecimals(2)
            spinbox.setRange(0.0, 999999.99)
            spinbox.setSingleStep(10.0)
            spinbox.setSuffix(" MT")
            grid.addWidget(spinbox, 1, column)
            self._rob_inputs[fuel_type] = spinbox
        editor_layout.addLayout(grid)

        actions = QHBoxLayout()
        self.save_button = QPushButton("Save Starting ROB")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save_starting_rob)
        actions.addWidget(self.save_button)
        actions.addStretch()
        editor_layout.addLayout(actions)
        layout.addWidget(editor)

        projection = QFrame()
        projection.setObjectName("panel")
        projection_layout = QVBoxLayout(projection)
        projection_layout.setContentsMargins(18, 16, 18, 16)
        projection_layout.setSpacing(10)
        projection_title = QLabel("PROJECTED ROB BY SCHEDULE EVENT")
        projection_title.setObjectName("fieldLabel")
        projection_layout.addWidget(projection_title)

        self.projection_table_model = ROBProjectionTableModel()
        self.projection_table = QTableView()
        self.projection_table.setModel(self.projection_table_model)
        self.projection_table.setAlternatingRowColors(True)
        self.projection_table.horizontalHeader().setStretchLastSection(True)
        projection_layout.addWidget(self.projection_table)

        self.final_rob_label = QLabel("Final ROB: ULSFO 0.00 MT   |   VLSFO 0.00 MT   |   MDO 0.00 MT")
        self.final_rob_label.setObjectName("fieldLabel")
        projection_layout.addWidget(self.final_rob_label)
        layout.addWidget(projection, 1)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("mutedText")
        layout.addWidget(self.status_label)

        self.refresh()

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self.vessel_label.setText("Vessel: Not configured")
            self.save_button.setEnabled(False)
            self._set_inputs_enabled(False)
            self._set_inputs_to_zero()
            self._clear_projection("No vessel configured.")
            self.status_label.setText("Configure a vessel before saving starting ROB.")
            return

        self.vessel_label.setText(f"Vessel: {vessel.name}  |  IMO {vessel.imo}")
        self.save_button.setEnabled(True)
        self._set_inputs_enabled(True)
        starting_rob = self._rob_service.load_starting_rob(vessel.id)
        for fuel_type, spinbox in self._rob_inputs.items():
            spinbox.setValue(starting_rob.quantity_for(fuel_type))
        self._refresh_projection(vessel.id)
        self.status_label.setText("Starting ROB loaded.")

    def _save_starting_rob(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            QMessageBox.warning(self, "Vessel required", "Configure a vessel before saving starting ROB.")
            return
        quantities = {
            fuel_type: spinbox.value()
            for fuel_type, spinbox in self._rob_inputs.items()
        }
        try:
            saved = self._rob_service.save_starting_rob(
                self._rob_service.build_starting_rob(vessel.id, quantities)
            )
        except Exception as exc:
            QMessageBox.warning(self, "Starting ROB not saved", str(exc))
            return
        for fuel_type, spinbox in self._rob_inputs.items():
            spinbox.setValue(saved.quantity_for(fuel_type))
        self._refresh_projection(vessel.id)
        self.status_label.setText("Starting ROB saved.")

    def _refresh_projection(self, vessel_id: int) -> None:
        timeline = self._schedule_service.get_timeline(vessel_id)
        if not timeline.rows:
            self._clear_projection("No schedule events available.")
            return
        try:
            consumption = self._consumption_service.calculate_schedule_consumption(vessel_id, timeline)
            projection = self._rob_service.project_schedule_rob(vessel_id, consumption)
        except Exception as exc:
            self._clear_projection(str(exc))
            return
        self.projection_table_model.set_rows(projection.rows)
        self.final_rob_label.setText(
            "Final ROB: "
            f"ULSFO {_format_mt(projection.final_rob_mt['ULSFO'])}   |   "
            f"VLSFO {_format_mt(projection.final_rob_mt['VLSFO'])}   |   "
            f"MDO {_format_mt(projection.final_rob_mt['MDO'])}"
        )

    def _clear_projection(self, message: str) -> None:
        self.projection_table_model.set_rows([])
        self.final_rob_label.setText(
            "Final ROB: ULSFO 0.00 MT   |   VLSFO 0.00 MT   |   MDO 0.00 MT"
            f"   |   {message}"
        )

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for spinbox in self._rob_inputs.values():
            spinbox.setEnabled(enabled)

    def _set_inputs_to_zero(self) -> None:
        for spinbox in self._rob_inputs.values():
            spinbox.setValue(0.0)


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
