from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, Qt
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

from fuel_consumption_calculator.calculations.consumption_engine import EventFuelConsumption
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES, OPERATING_MODES
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.vessel_service import VesselService
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
    ) -> None:
        super().__init__()
        self._vessel_service = vessel_service
        self._consumption_service = consumption_service
        self._schedule_service = schedule_service
        self._rate_inputs: dict[tuple[str, str], QDoubleSpinBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)
        layout.addWidget(PageHeader("Consumption", "Configure vessel fuel consumption rates."))

        self.vessel_label = QLabel("Vessel: Not configured")
        self.vessel_label.setObjectName("fieldLabel")
        layout.addWidget(self.vessel_label)

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

        layout.addWidget(matrix)

        actions = QHBoxLayout()
        self.save_button = QPushButton("Save Consumption Profile")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save_profile)
        actions.addWidget(self.save_button)
        actions.addStretch()
        layout.addLayout(actions)

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
        layout.addWidget(projection, 1)

        layout.addStretch()

        self.refresh()

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self.vessel_label.setText("Vessel: Not configured")
            self.save_button.setEnabled(False)
            self._set_inputs_enabled(False)
            self._set_rates_to_zero()
            self._clear_projection("No vessel configured.")
            self.status_label.setText("Configure a vessel before saving consumption rates.")
            return

        self.vessel_label.setText(f"Vessel: {vessel.name}  |  IMO {vessel.imo}")
        self.save_button.setEnabled(True)
        self._set_inputs_enabled(True)
        profile = self._consumption_service.load_profile(vessel.id)
        for key, spinbox in self._rate_inputs.items():
            spinbox.setValue(profile.rate_for(*key))
        self._refresh_projection(vessel.id)
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
