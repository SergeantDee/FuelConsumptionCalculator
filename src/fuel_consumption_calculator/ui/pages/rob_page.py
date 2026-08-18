from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
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
            _format_mt(row.projected_rob_mt["ULSFO"]),
            _format_mt(row.projected_rob_mt["VLSFO"]),
            _format_mt(row.projected_rob_mt["MDO"]),
        )
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and index.column() >= 3:
            rob_values = (
                row.projected_rob_mt["ULSFO"],
                row.projected_rob_mt["VLSFO"],
                row.projected_rob_mt["MDO"],
            )
            rob_value = rob_values[index.column() - 3]
            if rob_value is not None and rob_value < 0:
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

    def row_at(self, row: int) -> EventROBProjection | None:
        if not 0 <= row < len(self._rows):
            return None
        return self._rows[row]


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

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.content = QWidget()
        self.content.setMinimumWidth(900)
        layout = QVBoxLayout(self.content)
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
        self.projection_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.projection_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.projection_table.verticalHeader().setDefaultSectionSize(32)
        self.projection_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.projection_table.selectionModel().selectionChanged.connect(self._projection_selection_changed)
        projection_layout.addWidget(self.projection_table)

        details = QFrame()
        details.setObjectName("panel")
        details_grid = QGridLayout(details)
        details_grid.setContentsMargins(14, 12, 14, 12)
        details_grid.addWidget(QLabel("SELECTED EVENT CONSUMPTION"), 0, 0, 1, 3)
        self._consumed_labels: dict[str, QLabel] = {}
        for column, fuel_type in enumerate(FUEL_TYPES):
            details_grid.addWidget(QLabel(f"{fuel_type} Consumed"), 1, column)
            label = QLabel("0.00 MT")
            label.setObjectName("fieldLabel")
            details_grid.addWidget(label, 2, column)
            self._consumed_labels[fuel_type] = label
        projection_layout.addWidget(details)

        self.final_rob_label = QLabel("Final ROB: ULSFO 0.00 MT   |   VLSFO 0.00 MT   |   MDO 0.00 MT")
        self.final_rob_label.setObjectName("fieldLabel")
        projection_layout.addWidget(self.final_rob_label)
        layout.addWidget(projection, 1)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("mutedText")
        layout.addWidget(self.status_label)
        self.scroll.setWidget(self.content)
        root_layout.addWidget(self.scroll)

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
        if projection.rows:
            self.projection_table.selectRow(0)
        else:
            self._set_consumption_details(None)
        self.final_rob_label.setText(
            "Final ROB: "
            f"ULSFO {_format_mt(projection.final_rob_mt['ULSFO'])}   |   "
            f"VLSFO {_format_mt(projection.final_rob_mt['VLSFO'])}   |   "
            f"MDO {_format_mt(projection.final_rob_mt['MDO'])}"
        )

    def _clear_projection(self, message: str) -> None:
        self.projection_table_model.set_rows([])
        self._set_consumption_details(None)
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

    def _projection_selection_changed(self) -> None:
        selected = self.projection_table.selectionModel().selectedRows() if self.projection_table.selectionModel() else []
        row = self.projection_table_model.row_at(selected[0].row()) if selected else None
        self._set_consumption_details(row)

    def _set_consumption_details(self, row: EventROBProjection | None) -> None:
        for fuel_type, label in self._consumed_labels.items():
            label.setText(_format_mt(row.consumed_mt[fuel_type]) if row else "0.00 MT")


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
