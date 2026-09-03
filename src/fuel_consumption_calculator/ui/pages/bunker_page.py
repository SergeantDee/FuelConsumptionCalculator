from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from PySide6.QtCore import QAbstractTableModel, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
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
    QTableView,
    QVBoxLayout,
    QWidget,
)

from fuel_consumption_calculator.calculations.bunker_projection_engine import EventBunkerROBProjection
from fuel_consumption_calculator.calculations.port_bunker_projection import PortBunkerProjectionRow, build_port_bunker_projection
from fuel_consumption_calculator.domain.bunker import BunkerLiftLimit, BunkerPlanStatus, BunkerReceivingTankPlan, BunkerTankReceipt
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.voyage import ActualROBObservation
from fuel_consumption_calculator.domain.voyage_stages import build_voyage_stage_timeline
from fuel_consumption_calculator.services.bunker_service import BunkerService
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.rob_service import ROBService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.services.voyage_service import VoyageService
from fuel_consumption_calculator.ui.widgets.actual_rob_dialog import ActualROBDialog
from fuel_consumption_calculator.ui.widgets.fuel_display import FuelBadge, FuelTextDelegate, format_fuel_html
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader


class BunkerPlansTableModel(QAbstractTableModel):
    HEADERS = ("Sequence", "Port", "ULSFO", "VLSFO", "MDO", "Status")

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[BunkerPlanStatus] = []

    def rowCount(self, parent=None) -> int:
        return len(self._rows)

    def columnCount(self, parent=None) -> int:
        return len(self.HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        values = (
            row.plan.sequence_number,
            row.plan.port_snapshot,
            _format_mt(row.plan.quantity_for("ULSFO")),
            _format_mt(row.plan.quantity_for("VLSFO")),
            _format_mt(row.plan.quantity_for("MDO")),
            row.status,
        )
        if role == Qt.ItemDataRole.DisplayRole:
            return str(values[index.column()])
        if role == Qt.ItemDataRole.ForegroundRole and row.status == "STALE":
            return QColor("#f1c778")
        return None

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return self.HEADERS[section] if orientation == Qt.Orientation.Horizontal else str(section + 1)

    def set_rows(self, rows: list[BunkerPlanStatus]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row_at(self, row: int) -> BunkerPlanStatus | None:
        if not 0 <= row < len(self._rows):
            return None
        return self._rows[row]


class BunkerProjectionTableModel(QAbstractTableModel):
    HEADERS = ("Port", "ULSFO Arrival", "ULSFO Bunker", "ULSFO Departure", "VLSFO Arrival", "VLSFO Bunker", "VLSFO Departure", "MDO Arrival", "MDO Bunker", "MDO Departure")

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[EventBunkerROBProjection] = []

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
            _format_mt(row.arrival_rob_mt["ULSFO"]),
            _format_mt(row.bunker_mt["ULSFO"]),
            _format_mt(row.departure_rob_mt["ULSFO"]),
            _format_mt(row.arrival_rob_mt["VLSFO"]),
            _format_mt(row.bunker_mt["VLSFO"]),
            _format_mt(row.departure_rob_mt["VLSFO"]),
            _format_mt(row.arrival_rob_mt["MDO"]),
            _format_mt(row.bunker_mt["MDO"]),
            _format_mt(row.departure_rob_mt["MDO"]),
        )
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and index.column() in {1, 3, 4, 6, 7, 9}:
            rob_values = (row.arrival_rob_mt["ULSFO"], row.departure_rob_mt["ULSFO"], row.arrival_rob_mt["VLSFO"], row.departure_rob_mt["VLSFO"], row.arrival_rob_mt["MDO"], row.departure_rob_mt["MDO"])
            rob_value = rob_values[{1: 0, 3: 1, 4: 2, 6: 3, 7: 4, 9: 5}[index.column()]]
            if rob_value is not None and rob_value < 0:
                return QColor("#ff9b9b")
        return None

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return self.HEADERS[section] if orientation == Qt.Orientation.Horizontal else str(section + 1)

    def set_rows(self, rows: list[EventBunkerROBProjection]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()


class PortProjectionTableModel(QAbstractTableModel):
    HEADERS = ("Status", "Port", "Arrival UTC", "Arrival ROB", "ROB Source", "Max Lift", "Planned Bunker", "Plan Status", "Departure ROB", "Issue")

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[PortBunkerProjectionRow] = []

    def rowCount(self, parent=None) -> int:
        return len(self._rows)

    def columnCount(self, parent=None) -> int:
        return len(self.HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        values = (row.status, row.event.port, row.event.effective_arrival_at.strftime("%d %b %Y %H:%M"), _format_fuels(row.arrival_rob_mt), row.rob_source, _format_fuels(row.max_lift_mt), _format_fuels(row.planned_bunker_mt), row.plan_status, _format_fuels(row.departure_rob_mt), row.issue or "")
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole and index.column() in {3, 5, 6, 8}:
            return "ULSFO / VLSFO / MDO (MT)"
        if role == Qt.ItemDataRole.ForegroundRole and row.issue:
            return QColor("#f1c778")
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        return self.HEADERS[section] if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal else None

    def set_rows(self, rows: list[PortBunkerProjectionRow]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row_at(self, row: int) -> PortBunkerProjectionRow | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None


class ReceivingTanksDialog(QDialog):
    """Receiving plan with manual-over-auto advisory arrival estimates."""
    def __init__(self, service: BunkerService, plan, default_target: float, parent=None):
        super().__init__(parent)
        self._service, self._plan = service, plan
        self.setObjectName("receivingTanksDialog")
        self.setWindowTitle("Receiving Tanks")
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else self.geometry()
        width, height = min(1200, available.width() - 50), min(740, available.height() - 50)
        self.setMinimumSize(min(900, width), min(560, height))
        self.resize(width, height)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title_row = QHBoxLayout()
        title_icon = QLabel("◈")
        title_icon.setObjectName("receivingTitleIcon")
        title_row.addWidget(title_icon)
        title = QLabel("Receiving Tanks")
        title.setObjectName("receivingTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)
        hint = QLabel("Projected arrival uses the bunker event arrival UTC. Typing a value creates a manual override.")
        hint.setObjectName("receivingHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, 8)
        self.table.setObjectName("receivingTanksTable")
        self.table.setHorizontalHeaderLabels(("Select", "Tank", "Capacity (m³)", "Latest Actual (m³)", "Projected Arrival (m³)", "Source", "Target Fill (%)", "Available (m³)"))
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        for column, width in enumerate((70, 230, 120, 140, 160, 130, 135, 125)):
            self.table.setColumnWidth(column, width)
        layout.addWidget(self.table, 1)

        lower = QHBoxLayout()
        lower.setSpacing(12)
        incoming_card = QFrame()
        incoming_card.setObjectName("receivingIncomingCard")
        incoming = QFormLayout(incoming_card)
        incoming.setContentsMargins(14, 12, 14, 12)
        incoming.setHorizontalSpacing(16)
        incoming.setVerticalSpacing(8)
        self.batch_input = QComboBox(); self.batch_input.addItem("No incoming batch", None)
        for batch in service.list_fuel_batches(plan.vessel_id): self.batch_input.addItem(f"{batch.batch_name} ({batch.fuel_type})", batch.id)
        self.fuel_label = FuelBadge(None); self.density_label = QLabel("--")
        # Keep a distinct special-value sentinel so -50.0 °C remains a valid
        # API MPMS 11.1 input instead of being mistaken for "not entered".
        self.temperature_input = QDoubleSpinBox(); self.temperature_input.setRange(-50.1, 150); self.temperature_input.setDecimals(1); self.temperature_input.setSpecialValueText("Enter temperature")
        self.vcf_mode_input = QComboBox(); self.vcf_mode_input.addItems(("AUTO", "MANUAL"))
        self.vcf_input = QLineEdit(); self.vcf_input.setPlaceholderText("Manual VCF, e.g. 0.98500")
        self.auto_vcf_label = QLabel("— AUTO")
        incoming.addRow("Incoming Batch", self.batch_input); incoming.addRow("Fuel Type", self.fuel_label); incoming.addRow("Density @ 15 °C", self.density_label); incoming.addRow("Incoming Temperature °C", self.temperature_input); incoming.addRow("VCF Mode", self.vcf_mode_input); incoming.addRow("VCF", self.auto_vcf_label); incoming.addRow("Manual VCF", self.vcf_input)
        note = QLabel("AUTO calculates the API MPMS 11.1 / ASTM D1250-style VCF from the incoming batch density and entered incoming temperature. MANUAL is an explicit override.")
        note.setObjectName("receivingNote")
        note.setWordWrap(True)
        incoming.addRow(note)
        lower.addWidget(incoming_card, 3)

        summary_card = QFrame()
        summary_card.setObjectName("receivingSummaryCard")
        summary = QGridLayout(summary_card)
        summary.setContentsMargins(14, 12, 14, 12)
        summary.setHorizontalSpacing(12)
        summary.setVerticalSpacing(6)
        for row, label in enumerate(("Selected tanks", "Available volume", "Volume @15°C", "Effective VCF", "Density @15°C", "Incoming temperature", "Tank-based max lift")):
            summary.addWidget(QLabel(label), row, 0)
        self.selected_summary = QLabel("0")
        self.available_summary = QLabel("--")
        self.volume_15_summary = QLabel("--")
        self.effective_vcf_summary = QLabel("--")
        self.summary_density = QLabel("--")
        self.summary_temperature = QLabel("--")
        self.max_lift_summary = QLabel("--")
        for row, value in enumerate((self.selected_summary, self.available_summary, self.volume_15_summary, self.effective_vcf_summary, self.summary_density, self.summary_temperature, self.max_lift_summary)):
            value.setObjectName("receivingSummaryValue")
            summary.addWidget(value, row, 1)
        lower.addWidget(summary_card, 2)
        layout.addLayout(lower)

        actions = QHBoxLayout()
        self.use_latest_button = QPushButton("Use Latest Actual")
        self.use_latest_button.clicked.connect(self._use_latest)
        actions.addWidget(self.use_latest_button)
        self.use_estimate_button = QPushButton("Use Estimate")
        self.use_estimate_button.clicked.connect(self._use_estimate)
        actions.addWidget(self.use_estimate_button)
        actions.addWidget(QLabel("Target Fill"))
        self.apply_target_input = QDoubleSpinBox()
        self.apply_target_input.setRange(.01, 100)
        self.apply_target_input.setValue(default_target)
        self.apply_target_input.setSuffix(" %")
        actions.addWidget(self.apply_target_input)
        self.apply_target_button = QPushButton("Apply to Selected")
        self.apply_target_button.clicked.connect(self._apply_target_to_selected)
        actions.addWidget(self.apply_target_button)
        actions.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("receivingCancelButton")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton("Save Receiving Plan")
        self.save_button.setObjectName("receivingSaveButton")
        self.save_button.clicked.connect(self._save)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)
        persisted = {row.tank_id: row for row in service.list_receiving_tank_plan(plan)}; snapshot = service.load_incoming_fuel_snapshot(plan)
        if snapshot.fuel_batch_id is not None: self.batch_input.setCurrentIndex(next((i for i in range(self.batch_input.count()) if self.batch_input.itemData(i) == snapshot.fuel_batch_id), 0))
        existing = service.has_receiving_tank_plan(plan)
        self.vcf_mode_input.setCurrentText(snapshot.vcf_mode if existing else "AUTO")
        if snapshot.incoming_temperature_c is not None: self.temperature_input.setValue(snapshot.incoming_temperature_c)
        if snapshot.manual_vcf is not None: self.vcf_input.setText(f"{snapshot.manual_vcf:.5f}")
        candidates = [BunkerReceivingTankPlan(tank.id, persisted[tank.id].projected_arrival_volume_m3 if tank.id in persisted else None, persisted[tank.id].target_fill_percent if tank.id in persisted else default_target) for tank, _latest in service.list_eligible_receiving_tanks(plan.vessel_id)]
        estimates = service.resolve_receiving_tank_arrivals(plan, candidates)
        for row, (tank, latest) in enumerate(service.list_eligible_receiving_tanks(plan.vessel_id)):
            saved = persisted.get(tank.id); estimate = estimates[tank.id]; self.table.insertRow(row); check=QCheckBox(); check.setChecked(saved is not None); check.toggled.connect(self._update_summary); self.table.setCellWidget(row,0,check); item=QTableWidgetItem(tank.name); item.setData(Qt.ItemDataRole.UserRole,(tank.id,latest,estimate)); self.table.setItem(row,1,item); self.table.setItem(row,2,QTableWidgetItem(f"{tank.capacity_m3:.3f}")); self.table.setItem(row,3,QTableWidgetItem("--" if latest is None else f"{latest:.3f}")); projected=QLineEdit("" if estimate.projected_arrival_volume_m3 is None else f"{estimate.projected_arrival_volume_m3:.3f}"); projected.setProperty("manual_override", saved is not None and saved.projected_arrival_volume_m3 is not None); projected.textEdited.connect(lambda _text, field=projected: field.setProperty("manual_override", True)); projected.textChanged.connect(self._update_summary); target=QDoubleSpinBox(); target.setRange(.01,100); target.setValue(saved.target_fill_percent if saved else default_target); target.valueChanged.connect(self._update_summary); available="--" if estimate.projected_arrival_volume_m3 is None else f"{max(0.0, tank.capacity_m3 * target.value() / 100 - estimate.projected_arrival_volume_m3):.3f}"; self.table.setCellWidget(row,4,projected); source=QTableWidgetItem("Manual" if estimate.source == "MANUAL" else "Estimated" if estimate.source == "ESTIMATED" else "Unavailable"); source.setToolTip(estimate.issue or ""); self.table.setItem(row,5,source); self.table.setCellWidget(row,6,target); self.table.setItem(row,7,QTableWidgetItem(available))
        self.batch_input.currentIndexChanged.connect(self._batch_changed); self.vcf_mode_input.currentTextChanged.connect(self._vcf_mode_changed); self.temperature_input.valueChanged.connect(self._refresh_auto_vcf); self.temperature_input.valueChanged.connect(self._update_summary); self.vcf_input.textChanged.connect(self._update_summary); self._batch_changed(); self._vcf_mode_changed(); self._update_summary()

    def _update_summary(self):
        selected = sum(self.table.cellWidget(row, 0).isChecked() for row in range(self.table.rowCount()))
        self.selected_summary.setText(str(selected))
        batch = next((item for item in self._service.list_fuel_batches(self._plan.vessel_id) if item.id == self.batch_input.currentData()), None)
        effective_vcf = self._dialog_effective_vcf(batch)
        available = 0.0
        complete = selected > 0
        for row in range(self.table.rowCount()):
            if not self.table.cellWidget(row, 0).isChecked():
                continue
            try:
                capacity = float(self.table.item(row, 2).text())
                projected = float(self.table.cellWidget(row, 4).text())
            except (TypeError, ValueError):
                complete = False
                continue
            available += max(0.0, capacity * self.table.cellWidget(row, 6).value() / 100.0 - projected)
        volume_15 = available * effective_vcf if complete and effective_vcf is not None else None
        max_lift = volume_15 * batch.density_15_kg_m3 / 1000.0 if volume_15 is not None and batch is not None else None
        self.available_summary.setText(f"{available:.3f} m³" if complete else "--")
        self.volume_15_summary.setText("--" if volume_15 is None else f"{volume_15:.3f} m³")
        mode = self.vcf_mode_input.currentText()
        self.effective_vcf_summary.setText("--" if effective_vcf is None else f"{effective_vcf:.5f} {mode}")
        self.summary_density.setText("--" if batch is None else f"{batch.density_15_kg_m3:.3f} kg/m³")
        self.summary_temperature.setText("--" if mode != "AUTO" or self.temperature_input.value() == self.temperature_input.minimum() else f"{self.temperature_input.value():.1f} °C")
        self.max_lift_summary.setText("--" if max_lift is None else f"{max_lift:.3f} MT")

    def _dialog_effective_vcf(self, batch):
        if self.vcf_mode_input.currentText() == "MANUAL":
            try:
                value = float(self.vcf_input.text())
                return value if value > 0 else None
            except ValueError:
                return None
        if batch is None or self.temperature_input.value() == self.temperature_input.minimum():
            return None
        try:
            from fuel_consumption_calculator.calculations.automatic_vcf import calculate_automatic_vcf
            return calculate_automatic_vcf(batch.density_15_kg_m3, self.temperature_input.value(), batch.fuel_type)
        except ValueError:
            return None

    def _batch_changed(self):
        batch_id=self.batch_input.currentData(); batch=next((b for b in self._service.list_fuel_batches(self._plan.vessel_id) if b.id==batch_id),None); self.fuel_label.set_fuel_type(batch.fuel_type if batch else None); self.density_label.setText(f"{batch.density_15_kg_m3:.3f} kg/m3" if batch else "--"); self._refresh_auto_vcf(); self._update_summary()

    def _vcf_mode_changed(self):
        manual = self.vcf_mode_input.currentText() == "MANUAL"
        self.vcf_input.setEnabled(manual); self.auto_vcf_label.setVisible(not manual); self.temperature_input.setEnabled(not manual)
        self._refresh_auto_vcf(); self._update_summary()

    def _refresh_auto_vcf(self):
        if self.vcf_mode_input.currentText() != "AUTO": return
        batch = next((b for b in self._service.list_fuel_batches(self._plan.vessel_id) if b.id == self.batch_input.currentData()), None)
        if batch is None or self.temperature_input.value() == self.temperature_input.minimum(): self.auto_vcf_label.setText("Incoming bunker temperature required"); return
        try:
            from fuel_consumption_calculator.calculations.automatic_vcf import calculate_automatic_vcf
            self.auto_vcf_label.setText(f"{calculate_automatic_vcf(batch.density_15_kg_m3, self.temperature_input.value(), batch.fuel_type):.5f} AUTO")
        except ValueError as error: self.auto_vcf_label.setText(str(error))

    def _use_latest(self):
        row=self.table.currentRow()
        if row < 0: return
        latest=self.table.item(row,1).data(Qt.ItemDataRole.UserRole)[1]
        if latest is None: QMessageBox.warning(self,"Latest Actual unavailable","This tank has no latest actual volume."); return
        field=self.table.cellWidget(row,4); field.setText(str(latest)); field.setProperty("manual_override", True)

    def _use_estimate(self):
        row=self.table.currentRow()
        if row < 0: return
        _tank_id, _latest, estimate=self.table.item(row,1).data(Qt.ItemDataRole.UserRole)
        field=self.table.cellWidget(row,4); field.setText("" if estimate.projected_arrival_volume_m3 is None else f"{estimate.projected_arrival_volume_m3:.3f}"); field.setProperty("manual_override", False)

    def _apply_target_to_selected(self):
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 0).isChecked():
                self.table.cellWidget(row, 6).setValue(self.apply_target_input.value())
        self._update_summary()

    def _save(self):
        rows=[]
        for row in range(self.table.rowCount()):
            if not self.table.cellWidget(row,0).isChecked(): continue
            tank_id,_,_=self.table.item(row,1).data(Qt.ItemDataRole.UserRole); field=self.table.cellWidget(row,4); text=field.text().strip()
            rows.append(BunkerReceivingTankPlan(tank_id, float(text) if field.property("manual_override") and text else None, self.table.cellWidget(row,6).value()))
        mode = self.vcf_mode_input.currentText(); manual_vcf = float(self.vcf_input.text()) if mode == "MANUAL" and self.vcf_input.text().strip() else None
        temperature = self.temperature_input.value() if mode == "AUTO" and self.temperature_input.value() != self.temperature_input.minimum() else None
        try: self._service.save_receiving_tank_plan(self._plan, rows, self.batch_input.currentData(), manual_vcf, temperature, mode)
        except (ValueError, TypeError) as error: QMessageBox.warning(self,"Receiving plan not saved",str(error)); return
        self.accept()


class BunkerDistributionDialog(QDialog):
    def __init__(self, service: BunkerService, plan, parent=None):
        super().__init__(parent); self._service, self._plan = service, plan; self.setWindowTitle("Bunker Distribution"); self.resize(620, 360)
        layout = QVBoxLayout(self); self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(("Tank", "Available MT", "Receipt MT")); self.table.verticalHeader().setVisible(False); self.table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.table)
        incoming = service.load_incoming_fuel_snapshot(plan); batch = next((item for item in service.list_fuel_batches(plan.vessel_id) if item.id == incoming.fuel_batch_id), None)
        effective_vcf, _vcf_issue = service.effective_vcf(plan)
        self._fuel = batch.fuel_type if batch else None; self._total = plan.quantity_for(self._fuel) if self._fuel else 0.0
        rows = service.list_receiving_tank_plan(plan); tanks = {tank.id: tank for tank, _ in service.list_eligible_receiving_tanks(plan.vessel_id)}; projections = service.resolve_receiving_tank_arrivals(plan); saved = {item.tank_id: item for item in service.list_tank_receipts(plan)}
        for index, row in enumerate(rows):
            tank = tanks.get(row.tank_id); projection = projections.get(row.tank_id)
            if tank is None or projection is None or projection.projected_arrival_volume_m3 is None or incoming.density_15_kg_m3 is None or effective_vcf is None: capacity = None
            else:
                from fuel_consumption_calculator.calculations.tank_max_lift import SelectedReceivingTank, calculate_tank_max_lift
                capacity = calculate_tank_max_lift([SelectedReceivingTank(tank.id, tank.capacity_m3, projection.projected_arrival_volume_m3, row.target_fill_percent)], incoming_density_15_kg_m3=incoming.density_15_kg_m3, incoming_manual_vcf=effective_vcf).total_max_lift_mt
            self.table.insertRow(index); item=QTableWidgetItem(tank.name if tank else str(row.tank_id)); item.setData(Qt.ItemDataRole.UserRole, row.tank_id); self.table.setItem(index,0,item); self.table.setItem(index,1,QTableWidgetItem("--" if capacity is None else f"{capacity:.3f}")); value=QDoubleSpinBox(); value.setRange(0, capacity if capacity is not None else 999999.99); value.setDecimals(3); value.setValue(saved[row.tank_id].quantity_mt if row.tank_id in saved else 0); value.valueChanged.connect(self._update); self.table.setCellWidget(index,2,value)
        self.summary=QLabel(); self.summary.setObjectName("fieldLabel"); layout.addWidget(self.summary); buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject); layout.addWidget(buttons); self._update()

    def _update(self):
        allocated=sum(self.table.cellWidget(row,2).value() for row in range(self.table.rowCount())); remaining=self._total-allocated; self.summary.setText(f"Aggregate Bunker: {self._total:.2f} MT   |   Allocated: {allocated:.2f} MT   |   Remaining: {remaining:.2f} MT")

    def _save(self):
        if self._fuel is None: QMessageBox.warning(self,"Incoming fuel required","Select an incoming fuel batch before distributing bunker."); return
        rows=[BunkerTankReceipt(self.table.item(row,0).data(Qt.ItemDataRole.UserRole),self._fuel,self.table.cellWidget(row,2).value(),"") for row in range(self.table.rowCount())]
        try: self._service.save_tank_receipts(self._plan,rows)
        except ValueError as error: QMessageBox.warning(self,"Distribution not saved",str(error)); return
        self.accept()


class BunkerPage(QWidget):
    actual_sounding_saved = Signal()
    def __init__(
        self,
        vessel_service: VesselService,
        bunker_service: BunkerService,
        schedule_service: ScheduleService,
        consumption_service: ConsumptionService,
        rob_service: ROBService,
        voyage_service: VoyageService,
    ) -> None:
        super().__init__()
        self._vessel_service = vessel_service
        self._bunker_service = bunker_service
        self._schedule_service = schedule_service
        self._consumption_service = consumption_service
        self._rob_service = rob_service
        self._voyage_service = voyage_service
        self._events: list[ScheduleEvent] = []
        self._last_projection_rows: list[PortBunkerProjectionRow] = []
        self._capacity_inputs: dict[str, QDoubleSpinBox] = {}
        self._target_inputs: dict[str, QDoubleSpinBox] = {}
        self._planned_inputs: dict[str, QDoubleSpinBox] = {}
        self._target_rob_labels: dict[str, QLabel] = {}
        self._arrival_rob_labels: dict[str, QLabel] = {}
        self._max_lift_labels: dict[str, QLabel] = {}
        self._capacity_field_labels: dict[str, QLabel] = {}
        self._lift_limits: dict[str, BunkerLiftLimit] = {}
        self._loading_plan = False

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.content = QWidget()
        self.content.setMinimumWidth(1050)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)
        layout.addWidget(PageHeader("Bunker Planner", "Plan bunker lifts after arrival and before port consumption."))

        self.vessel_label = QLabel("Vessel: Not configured")
        self.vessel_label.setObjectName("fieldLabel")
        layout.addWidget(self.vessel_label)

        sounding_panel = QFrame()
        sounding_panel.setObjectName("panel")
        sounding_layout = QVBoxLayout(sounding_panel)
        sounding_layout.setContentsMargins(18, 16, 18, 16)
        sounding_layout.addWidget(QLabel("ACTUAL SOUNDING ROB"))
        self.actual_sounding_label = QLabel("No Actual Sounding ROB recorded")
        self.actual_sounding_label.setObjectName("mutedText")
        self.actual_sounding_label.setWordWrap(True)
        sounding_layout.addWidget(self.actual_sounding_label)
        self.update_sounding_button = QPushButton("Update Actual Sounding ROB")
        self.update_sounding_button.setObjectName("primaryButton")
        self.update_sounding_button.clicked.connect(self._update_actual_sounding)
        sounding_layout.addWidget(self.update_sounding_button)
        layout.addWidget(sounding_panel)
        actions = QHBoxLayout()
        self.capacity_settings_button = QPushButton("Capacity Settings")
        self.capacity_settings_button.clicked.connect(self._open_capacity_settings)
        actions.addWidget(self.capacity_settings_button)
        actions.addStretch()
        layout.addLayout(actions)

        self.capacity_panel = QFrame()
        capacity_panel = self.capacity_panel
        capacity_panel.setObjectName("panel")
        capacity_grid = QGridLayout(capacity_panel)
        capacity_grid.setContentsMargins(18, 16, 18, 16)
        capacity_grid.addWidget(QLabel("VESSEL CAPACITY SETTINGS"), 0, 0, 1, 3)
        capacity_grid.addWidget(QLabel("Fuel"), 1, 0)
        capacity_grid.addWidget(QLabel("Max Capacity"), 1, 1)
        capacity_grid.addWidget(QLabel("Default Target %"), 1, 2)
        for row, fuel_type in enumerate(FUEL_TYPES, start=2):
            capacity_grid.addWidget(QLabel(fuel_type), row, 0)
            capacity_input = _spinbox(" MT", 0, 999999.99, 10)
            target_input = _spinbox(" %", 0, 100, 1)
            target_input.setValue(90)
            capacity_grid.addWidget(capacity_input, row, 1)
            capacity_grid.addWidget(target_input, row, 2)
            self._capacity_inputs[fuel_type] = capacity_input
            self._target_inputs[fuel_type] = target_input
            capacity_input.valueChanged.connect(self._update_lift_limits)
            target_input.valueChanged.connect(self._update_lift_limits)
        self.save_capacity_button = QPushButton("Save Capacity Settings")
        self.save_capacity_button.setObjectName("primaryButton")
        self.save_capacity_button.clicked.connect(self._save_capacities)
        capacity_grid.addWidget(self.save_capacity_button, 5, 0, 1, 3)
        self.plan_panel = QFrame()
        plan_panel = self.plan_panel
        plan_panel.setObjectName("panel")
        plan_layout = QVBoxLayout(plan_panel)
        plan_layout.setContentsMargins(18, 16, 18, 16)
        self.plan_port_title = QLabel("PLANNED BUNKER PORT")
        self.plan_port_title.setVisible(False)
        plan_layout.addWidget(self.plan_port_title)

        self.event_combo = QComboBox()
        self.event_combo.currentIndexChanged.connect(self._selection_changed)
        self.event_combo.setVisible(False)
        plan_layout.addWidget(self.event_combo)
        self.plan_status_label = QLabel("Status: DRAFT")
        self.plan_status_label.setObjectName("fieldLabel")
        plan_layout.addWidget(self.plan_status_label)
        fuel_cards = QHBoxLayout()
        fuel_cards.setSpacing(12)
        for fuel_type in FUEL_TYPES:
            card = QFrame()
            card.setObjectName("panel")
            card_grid = QGridLayout(card)
            card_grid.setContentsMargins(14, 12, 14, 12)
            title = FuelBadge(fuel_type)
            card_grid.addWidget(title, 0, 0, 1, 2)
            capacity_label = QLabel("0.00 MT")
            target_label = QLabel("90.00 %")
            target_rob_label = QLabel("0.00 MT")
            arrival_label = QLabel("0.00 MT")
            max_lift_label = QLabel("0.00 MT")
            planned_input = _spinbox(" MT", 0, 999999.99, 10)
            for label_row, (label_text, value_widget) in enumerate(
                (
                    ("Capacity", capacity_label),
                    ("Target %", target_label),
                    ("Target ROB", target_rob_label),
                    ("Arrival ROB", arrival_label),
                    ("Max Lift", max_lift_label),
                    ("Planned Lift", planned_input),
                ),
                start=1,
            ):
                field = QLabel(label_text)
                field.setObjectName("fieldLabel")
                card_grid.addWidget(field, label_row, 0)
                card_grid.addWidget(value_widget, label_row, 1)
                if label_text == "Capacity":
                    self._capacity_field_labels[fuel_type] = field
            self._target_rob_labels[fuel_type] = target_rob_label
            self._arrival_rob_labels[fuel_type] = arrival_label
            self._max_lift_labels[fuel_type] = max_lift_label
            self._planned_inputs[fuel_type] = planned_input
            planned_input.valueChanged.connect(self._planned_quantity_changed)
            setattr(self, f"_{fuel_type.lower()}_capacity_label", capacity_label)
            setattr(self, f"_{fuel_type.lower()}_target_label", target_label)
            fuel_cards.addWidget(card)
        plan_layout.addLayout(fuel_cards)
        actions = QHBoxLayout()
        self.save_plan_button = QPushButton("Save Planned Bunker")
        self.save_plan_button.setObjectName("primaryButton")
        self.save_plan_button.clicked.connect(self._save_plan)
        self.confirm_plan_button = QPushButton("Confirm Planned Bunker")
        self.confirm_plan_button.clicked.connect(self._confirm_plan)
        self.use_max_button = QPushButton("Use Max Lift")
        self.use_max_button.clicked.connect(self._use_max_lift)
        self.receiving_tanks_button = QPushButton("Receiving Tanks...")
        self.receiving_tanks_button.clicked.connect(self._open_receiving_tanks)
        self.bunker_distribution_button = QPushButton("Bunker Distribution...")
        self.bunker_distribution_button.clicked.connect(self._open_bunker_distribution)
        self.clear_plan_button = QPushButton("Clear Bunker Plan")
        self.clear_plan_button.setObjectName("dangerButton")
        self.clear_plan_button.clicked.connect(self._clear_plan)
        actions.addWidget(self.save_plan_button)
        actions.addWidget(self.confirm_plan_button)
        actions.addWidget(self.use_max_button)
        actions.addWidget(self.receiving_tanks_button)
        actions.addWidget(self.bunker_distribution_button)
        self.receiving_summary_label = QLabel("Receiving tanks not configured")
        self.receiving_summary_label.setObjectName("mutedText")
        actions.addWidget(self.receiving_summary_label)
        actions.addWidget(self.clear_plan_button)
        actions.addStretch()
        plan_layout.addLayout(actions)

        self.plans_model = BunkerPlansTableModel()
        self.plans_table = QTableView()
        self.plans_table.setModel(self.plans_model)
        self.plans_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.plans_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.plans_table.verticalHeader().setDefaultSectionSize(32)
        self.plans_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.projection_model = PortProjectionTableModel()
        self.projection_table = QTableView()
        self.projection_table.setModel(self.projection_model)
        self._fuel_text_delegate = FuelTextDelegate(self.projection_table)
        for column in (3, 5, 6, 8): self.projection_table.setItemDelegateForColumn(column, self._fuel_text_delegate)
        self.projection_table.verticalHeader().setDefaultSectionSize(32)
        self.projection_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.projection_table.horizontalHeader().setStretchLastSection(True)
        self.projection_table.doubleClicked.connect(self._open_port_details)
        layout.addWidget(QLabel("PORT PROJECTION"))
        layout.addWidget(self.projection_table, 1)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("mutedText")
        layout.addWidget(self.status_label)
        self.scroll.setWidget(self.content)
        root_layout.addWidget(self.scroll)
        self.refresh()

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self.actual_sounding_label.setText("No Actual Sounding ROB recorded")
            self.update_sounding_button.setEnabled(False)
            self.vessel_label.setText("Vessel: Not configured")
            self._set_controls_enabled(False)
            return

        self.update_sounding_button.setEnabled(True)
        observations = self._voyage_service.list_actual_rob_observations(vessel.id)
        latest = max(observations, key=lambda item: _utc_instant(item.effective_at_utc), default=None)
        if latest is None:
            self.actual_sounding_label.setText("No Actual Sounding ROB recorded")
        else:
            quantities = " | ".join(f"{fuel} {latest.quantities_mt.get(fuel):.2f} MT" for fuel in FUEL_TYPES)
            remarks = f" | {latest.remarks}" if latest.remarks else ""
            self.actual_sounding_label.setText(f"Effective: {_utc_instant(latest.effective_at_utc):%d %b %Y %H:%M UTC} | {quantities}{remarks}")
        self.vessel_label.setText(f"Vessel: {vessel.name}  |  IMO {vessel.imo}")
        self._set_controls_enabled(True)
        self._events = self._schedule_service.list_events(vessel.id)
        self._load_capacities(vessel.id)
        self._populate_events()
        self._refresh_projection(vessel.id)
        self._selection_changed()
        self.status_label.setText("Bunker planner loaded." if self._events else "No schedule events available.")

    def _update_actual_sounding(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            return
        observations = self._voyage_service.list_actual_rob_observations(vessel.id)
        latest = max(observations, key=lambda item: _utc_instant(item.effective_at_utc), default=None)
        dialog = ActualROBDialog(latest.quantities_mt if latest else None, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        try:
            self._voyage_service.save_actual_rob_observation(
                ActualROBObservation(
                    id=None,
                    vessel_id=vessel.id,
                    effective_at_utc=values["effective_at_utc"],
                    quantities_mt={fuel: values[fuel] for fuel in FUEL_TYPES},
                    remarks=values["remarks"],
                )
            )
        except Exception as exc:
            QMessageBox.warning(self, "Actual Sounding ROB not saved", str(exc))
            return
        self.refresh()
        self.actual_sounding_saved.emit()

    def _load_capacities(self, vessel_id: int) -> None:
        profile = self._bunker_service.load_capacity_profile(vessel_id)
        for fuel_type in FUEL_TYPES:
            capacity = profile.capacity_for(fuel_type)
            self._capacity_inputs[fuel_type].setValue(capacity.maximum_capacity_mt)
            self._target_inputs[fuel_type].setValue(capacity.target_fill_percent)

    def _populate_events(self) -> None:
        self.event_combo.blockSignals(True)
        self.event_combo.clear()
        for event in self._events:
            self.event_combo.addItem(f"#{event.sequence_number} {event.port} - {event.arrival_at:%d %b %Y %H:%M}")
        self.event_combo.blockSignals(False)

    def _save_capacities(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            return
        data = {fuel_type: (self._capacity_inputs[fuel_type].value(), self._target_inputs[fuel_type].value()) for fuel_type in FUEL_TYPES}
        try:
            self._bunker_service.save_capacity_profile(self._bunker_service.build_capacity_profile(vessel.id, data))
        except Exception as exc:
            QMessageBox.warning(self, "Capacity settings not saved", str(exc))
            return
        self._refresh_projection(vessel.id)
        self._update_lift_limits()
        self.status_label.setText("Capacity settings saved.")

    def _save_plan(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        event = self._selected_event()
        if vessel is None or event is None:
            QMessageBox.warning(self, "Schedule event required", "Select a schedule event before saving a bunker plan.")
            return
        quantities = {fuel_type: self._planned_inputs[fuel_type].value() for fuel_type in FUEL_TYPES}
        try:
            plan = self._bunker_service.build_plan(vessel_id=vessel.id, event=event, quantities=quantities, lift_limits=None if self._has_tank_plan(event) and self._bunker_service.tank_based_max_lift(self._current_event_plan()) is None else self._lift_limits)
            self._bunker_service.save_plan(plan)
        except Exception as exc:
            QMessageBox.warning(self, "Bunker plan not saved", str(exc))
            return
        self._refresh_projection(vessel.id)
        self._selection_changed()
        self.status_label.setText("Bunker plan saved as DRAFT.")

    def _confirm_plan(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        event = self._selected_event()
        if vessel is None or event is None:
            QMessageBox.warning(self, "Schedule event required", "Select a schedule event before confirming a bunker plan.")
            return
        matching_status = self._matching_plan_status(vessel.id, event)
        if matching_status is None:
            QMessageBox.warning(self, "Bunker plan required", "Save a planned bunker before confirming it.")
            return
        if matching_status.status == "STALE":
            QMessageBox.warning(self, "Stale bunker plan", "This bunker plan no longer matches the current schedule event.")
            return
        if self._has_tank_plan(event):
            result = self._bunker_service.tank_based_max_lift(matching_status.plan)
            if result is None or result.total_max_lift_mt is None:
                QMessageBox.warning(self, "Receiving plan incomplete", "Complete the Receiving Tanks plan before confirming this bunker quantity.")
                return
            if sum(self._planned_inputs[fuel].value() for fuel in FUEL_TYPES) > round(result.total_max_lift_mt, 2):
                QMessageBox.warning(self, "Bunker plan not confirmed", "Planned Lift exceeds calculated Max Lift.")
                return
        try:
            self._bunker_service.confirm_plan(matching_status.plan)
        except Exception as exc:
            QMessageBox.warning(self, "Bunker plan not confirmed", str(exc))
            return
        self._refresh_projection(vessel.id)
        self._selection_changed()
        self.status_label.setText("Bunker plan confirmed.")

    def _clear_plan(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            return
        selected_plan = self._selected_plan_status()
        if selected_plan is not None:
            self._bunker_service.clear_plan(
                vessel.id,
                selected_plan.plan.sequence_number,
                selected_plan.plan.port_snapshot,
                selected_plan.plan.arrival_snapshot,
            )
        else:
            event = self._selected_event()
            if event is None:
                return
            self._bunker_service.clear_plan(vessel.id, event.sequence_number, event.port)
        for spinbox in self._planned_inputs.values():
            spinbox.setValue(0)
        self._refresh_projection(vessel.id)
        self.status_label.setText("Bunker plan cleared.")

    def _selection_changed(self) -> None:
        self._loading_plan = True
        for spinbox in self._planned_inputs.values():
            spinbox.setValue(0)
        vessel = self._vessel_service.get_active_vessel()
        event = self._selected_event()
        if vessel is not None and event is not None:
            matching_status = self._matching_plan_status(vessel.id, event)
            if matching_status is not None:
                for fuel_type in FUEL_TYPES:
                    self._planned_inputs[fuel_type].setValue(matching_status.plan.quantity_for(fuel_type))
                self.plan_status_label.setText(f"Status: {matching_status.status}")
            else:
                self.plan_status_label.setText("Status: DRAFT")
        else:
            self.plan_status_label.setText("Status: DRAFT")
        self._loading_plan = False
        self._update_lift_limits()

    def _planned_quantity_changed(self) -> None:
        if self._loading_plan:
            return
        vessel = self._vessel_service.get_active_vessel()
        event = self._selected_event()
        if vessel is None or event is None:
            return
        matching_status = self._matching_plan_status(vessel.id, event)
        if matching_status is None:
            self.plan_status_label.setText("Status: DRAFT")
            return
        changed = any(
            abs(self._planned_inputs[fuel_type].value() - matching_status.plan.quantity_for(fuel_type)) > 0.001
            for fuel_type in FUEL_TYPES
        )
        if changed:
            self.plan_status_label.setText("Status: DRAFT")
        else:
            self.plan_status_label.setText(f"Status: {matching_status.status}")

    def _use_max_lift(self) -> None:
        for fuel_type, limit in self._lift_limits.items():
            if limit.max_lift_mt is not None:
                self._planned_inputs[fuel_type].setValue(limit.max_lift_mt)

    def _open_receiving_tanks(self) -> None:
        vessel=self._vessel_service.get_active_vessel(); event=self._selected_event()
        if vessel is None or event is None: return
        plan=self._bunker_service.build_plan(vessel_id=vessel.id,event=event,quantities={fuel: self._planned_inputs[fuel].value() for fuel in FUEL_TYPES})
        default_target=next(iter(self._target_inputs.values())).value() if self._target_inputs else 90
        if ReceivingTanksDialog(self._bunker_service,plan,default_target,self).exec() == QDialog.DialogCode.Accepted:
            self._refresh_after_receiving_plan_save(vessel.id)

    def _refresh_after_receiving_plan_save(self, vessel_id: int) -> None:
        """Reload the current event's persisted receiving-plan authority after save."""
        self._refresh_projection(vessel_id)
        self._selection_changed()
        self.status_label.setText("Receiving tank plan saved as DRAFT.")

    def _open_bunker_distribution(self) -> None:
        plan = self._current_event_plan()
        if plan is None or not self._bunker_service.has_receiving_tank_plan(plan):
            QMessageBox.warning(self, "Receiving plan required", "Configure selected receiving tanks before distributing bunker.")
            return
        if BunkerDistributionDialog(self._bunker_service, plan, self).exec() == QDialog.DialogCode.Accepted:
            self.status_label.setText("Bunker tank distribution saved.")

    def _refresh_projection(self, vessel_id: int) -> None:
        plan_statuses = self._bunker_service.list_plan_statuses(vessel_id, self._events)
        self.plans_model.set_rows(plan_statuses)
        timeline = self._schedule_service.get_timeline(vessel_id)
        if not timeline.rows:
            self.projection_model.set_rows([])
            self._last_projection_rows = []
            return
        try:
            profile = self._consumption_service.load_profile(vessel_id)
            voyage_plan = self._voyage_service.calculate_plan(vessel_id, self._events, profile)
            voyage_result = self._voyage_service.calculate_consumption_for_plan(
                events=self._events, timeline=timeline, plan=voyage_plan, profile=profile,
            )
            starting_rob = self._rob_service.load_starting_rob(vessel_id)
            observations = self._voyage_service.list_actual_rob_observations(vessel_id)
            additions = {
                event.id: {fuel: status.plan.quantity_for(fuel) for fuel in FUEL_TYPES}
                for event in self._events
                for status in plan_statuses
                if status.status == "CONFIRMED" and status.plan.sequence_number == event.sequence_number
            }
            authoritative_timeline = build_voyage_stage_timeline(
                self._events, voyage_plan, starting_rob, port_breakdowns=voyage_result.port_breakdowns,
                rob_observations=observations, port_bunker_additions=additions,
            )
            projection = build_port_bunker_projection(
                self._events, authoritative_timeline, plan_statuses,
                self._bunker_service.load_capacity_profile(vessel_id), observations,
            )
        except Exception as exc:
            self.projection_model.set_rows([])
            self._last_projection_rows = []
            self.status_label.setText(str(exc))
            return
        self._last_projection_rows = projection
        self.projection_model.set_rows(projection)

    def _update_lift_limits(self) -> None:
        event = self._selected_event()
        if event is None:
            return
        projection_row = next((row for row in self._last_projection_rows if row.event.sequence_number == event.sequence_number), None)
        arrival_rob = projection_row.arrival_rob_mt if projection_row else {fuel_type: None for fuel_type in FUEL_TYPES}
        profile = self._bunker_service.build_capacity_profile(
            self._vessel_service.get_active_vessel().id if self._vessel_service.get_active_vessel() else 0,
            {fuel_type: (self._capacity_inputs[fuel_type].value(), self._target_inputs[fuel_type].value()) for fuel_type in FUEL_TYPES},
        )
        self._lift_limits = self._bunker_service.calculate_lift_limits(
            profile,
            arrival_rob,
            {fuel_type: self._target_inputs[fuel_type].value() for fuel_type in FUEL_TYPES},
        )
        plan = self._current_event_plan()
        tank_plan = plan is not None and self._bunker_service.has_receiving_tank_plan(plan)
        receiving_rows = self._bunker_service.list_receiving_tank_plan(plan) if tank_plan else []
        incoming = self._bunker_service.load_incoming_fuel_snapshot(plan) if tank_plan else None
        effective_vcf, vcf_issue = self._bunker_service.effective_vcf(plan) if tank_plan else (None, None)
        batches = self._bunker_service.list_fuel_batches(plan.vessel_id) if tank_plan else []
        batch = next((item for item in batches if item.id == incoming.fuel_batch_id), None) if incoming else None
        tanks = {tank.id: tank for tank, _latest in self._bunker_service.list_eligible_receiving_tanks(plan.vessel_id)} if tank_plan else {}
        projections = self._bunker_service.resolve_receiving_tank_arrivals(plan, receiving_rows) if tank_plan else {}
        unavailable_arrivals = sum(
            1 for row in receiving_rows
            if row.tank_id not in tanks
            or projections.get(row.tank_id) is None
            or projections[row.tank_id].projected_arrival_volume_m3 is None
        )
        tank_result = self._bunker_service.tank_based_max_lift(plan) if tank_plan and not unavailable_arrivals else None
        if tank_plan:
            selected_count_label = f"{len(receiving_rows)} {'tank' if len(receiving_rows) == 1 else 'tanks'} selected"
            selected_capacity_m3 = sum(tanks[row.tank_id].capacity_m3 for row in receiving_rows if row.tank_id in tanks)
            for fuel_type in FUEL_TYPES:
                self._capacity_field_labels[fuel_type].setText("Legacy Capacity")
            if batch is not None:
                self._capacity_field_labels[batch.fuel_type].setText("Receiving Capacity")
                getattr(self, f"_{batch.fuel_type.lower()}_capacity_label").setText(f"{selected_capacity_m3:.3f} m³")
            if tank_result is None or tank_result.total_max_lift_mt is None:
                reasons = []
                if unavailable_arrivals:
                    suffix = "tank" if unavailable_arrivals == 1 else "tanks"
                    reasons.append(f"Projected arrival unavailable for {unavailable_arrivals} selected {suffix}")
                if vcf_issue:
                    reasons.append(vcf_issue)
                self.receiving_summary_label.setText(selected_count_label + " · " + "; ".join(reasons or ["Max Lift unavailable"]))
                self._lift_limits = {fuel: replace(limit, max_lift_mt=None) for fuel, limit in self._lift_limits.items()}
            else:
                self.receiving_summary_label.setText(f"{selected_count_label} · {tank_result.total_available_volume_m3:.3f} m³ available")
                self._lift_limits = {fuel: replace(limit, max_lift_mt=tank_result.total_max_lift_mt if batch and fuel == batch.fuel_type else 0.0) for fuel, limit in self._lift_limits.items()}
                if sum(self._planned_inputs[fuel].value() for fuel in FUEL_TYPES) > tank_result.total_max_lift_mt + 0.001:
                    self.receiving_summary_label.setText("Receiving plan issue: Planned Lift exceeds refreshed Max Lift")
        else:
            self.receiving_summary_label.setText("Receiving tanks not configured")
        for fuel_type, limit in self._lift_limits.items():
            if not tank_plan or batch is None or fuel_type != batch.fuel_type:
                getattr(self, f"_{fuel_type.lower()}_capacity_label").setText(_format_mt(limit.capacity_mt))
            if not tank_plan:
                self._capacity_field_labels[fuel_type].setText("Capacity")
            getattr(self, f"_{fuel_type.lower()}_target_label").setText(f"{limit.target_fill_percent:.2f} %")
            self._target_rob_labels[fuel_type].setText(_format_mt(limit.target_rob_mt))
            self._arrival_rob_labels[fuel_type].setText(_format_mt(limit.arrival_rob_mt))
            self._max_lift_labels[fuel_type].setText(_format_mt(limit.max_lift_mt))
            self._planned_inputs[fuel_type].setMaximum(limit.max_lift_mt if limit.max_lift_mt is not None and not tank_plan else 999999.99)

    def _current_event_plan(self):
        vessel=self._vessel_service.get_active_vessel(); event=self._selected_event()
        if vessel is None or event is None: return None
        return self._bunker_service.build_plan(vessel_id=vessel.id,event=event,quantities={fuel: self._planned_inputs[fuel].value() for fuel in FUEL_TYPES})

    def _has_tank_plan(self, event):
        plan=self._current_event_plan()
        return plan is not None and self._bunker_service.has_receiving_tank_plan(plan)

    def _selected_event(self) -> ScheduleEvent | None:
        index = self.event_combo.currentIndex()
        if not 0 <= index < len(self._events):
            return None
        return self._events[index]

    def _selected_plan_status(self) -> BunkerPlanStatus | None:
        selected_rows = self.plans_table.selectionModel().selectedRows() if self.plans_table.selectionModel() else []
        if not selected_rows:
            return None
        return self.plans_model.row_at(selected_rows[0].row())

    def _matching_plan_status(self, vessel_id: int, event: ScheduleEvent) -> BunkerPlanStatus | None:
        arrival_snapshot = event.effective_arrival_at.isoformat(timespec="minutes")
        for status in self._bunker_service.list_plan_statuses(vessel_id, self._events):
            if (
                status.plan.sequence_number == event.sequence_number
                and status.plan.port_snapshot == event.port
                and status.plan.arrival_snapshot == arrival_snapshot
            ):
                return status
        return None

    def _open_port_details(self, index) -> None:
        row = self.projection_model.row_at(index.row())
        if row is None:
            return

        event_index = next(
            (
                position
                for position, event in enumerate(self._events)
                if event.id == row.event.id
            ),
            -1,
        )
        if event_index >= 0:
            # Keep the existing hidden selector as the authority for
            # save / confirm / clear bunker-plan operations.
            self.event_combo.setCurrentIndex(event_index)

        details = QDialog(self)
        details.setWindowTitle(f"Port Bunker Details - {row.event.port}")
        details.resize(980, 650)

        dialog_layout = QVBoxLayout(details)
        dialog_layout.setContentsMargins(12, 12, 12, 12)
        dialog_layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(12)

        scroll.setWidget(scroll_content)
        dialog_layout.addWidget(scroll)

        # Fixed port context: the operator already selected this row.
        heading = QLabel(row.event.port)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        port_meta = QLabel(
            f"Arrival: {row.event.effective_arrival_at:%d %b %Y %H:%M} UTC"
            f"  |  Status: {row.status}"
        )
        layout.addWidget(port_meta)

        # The aggregate voyage projection and tank forecast remain separate
        # authorities.  The latter is display-only bunker-space advice.
        vessel = self._vessel_service.get_active_vessel()
        arrival_bunker, arrival_bunker_issue = self._bunker_service.bunker_tank_rob_at(
            vessel.id, row.event.effective_arrival_at,
        ) if vessel else ({fuel: None for fuel in FUEL_TYPES}, "Vessel unavailable.")
        current_bunker, current_bunker_issue = self._bunker_service.bunker_tank_rob_at(
            vessel.id, datetime.now(timezone.utc),
        ) if vessel else ({fuel: None for fuel in FUEL_TYPES}, "Vessel unavailable.")
        end_at = row.event.effective_departure_at or row.event.effective_arrival_at
        eoe_bunker, eoe_bunker_issue = self._bunker_service.bunker_tank_rob_at(
            vessel.id, end_at,
        ) if vessel else ({fuel: None for fuel in FUEL_TYPES}, "Vessel unavailable.")

        summary_row = QHBoxLayout()
        summary_row.setSpacing(12)
        event_panel = _detail_card("ARRIVAL SUMMARY")
        event_grid = QGridLayout(); event_panel.layout().addItem(event_grid)
        event_grid.addWidget(QLabel("Arrival ROB Source"), 0, 0); event_grid.addWidget(QLabel(row.rob_source), 0, 1)
        event_grid.addWidget(QLabel("Arrival Time UTC"), 1, 0); event_grid.addWidget(QLabel(row.event.effective_arrival_at.strftime("%d %b %Y %H:%M")), 1, 1)
        event_grid.addWidget(QLabel("Vessel / IMO"), 2, 0); event_grid.addWidget(QLabel(f"{vessel.name} / {vessel.imo}" if vessel else "—"), 2, 1)
        summary_row.addWidget(event_panel, 2)
        total_panel = _detail_card("TOTAL VESSEL ROB")
        total_grid = QGridLayout(); total_panel.layout().addItem(total_grid)
        total_grid.addWidget(QLabel("Arrival Total ROB"), 0, 0); total_grid.addWidget(QLabel(_format_fuels(row.arrival_rob_mt)), 0, 1)
        total_grid.addWidget(QLabel("EOE ROB (end of current event)"), 1, 0); total_grid.addWidget(QLabel(_format_fuels(row.departure_rob_mt)), 1, 1)
        total_grid.addWidget(QLabel("Aggregate voyage authority"), 2, 0, 1, 2)
        summary_row.addWidget(total_panel, 3)
        bunker_panel = _detail_card("BUNKER TANKS ROB")
        bunker_grid = QGridLayout(); bunker_panel.layout().addItem(bunker_grid)
        bunker_grid.addWidget(QLabel("Arrival Bunker Tanks ROB"), 0, 0); bunker_grid.addWidget(QLabel(_format_fuels(arrival_bunker)), 0, 1)
        bunker_grid.addWidget(QLabel("Current Bunker Tanks ROB (now)"), 1, 0); bunker_grid.addWidget(QLabel(_format_fuels(current_bunker)), 1, 1)
        bunker_grid.addWidget(QLabel("EOE Bunker Tanks ROB"), 2, 0); bunker_grid.addWidget(QLabel(_format_fuels(eoe_bunker)), 2, 1)
        bunker_grid.addWidget(QLabel(arrival_bunker_issue or current_bunker_issue or eoe_bunker_issue or "Tank-forecast advisory only"), 3, 0, 1, 2)
        summary_row.addWidget(bunker_panel, 3)
        explanation = _detail_card("WHAT'S THE DIFFERENCE?")
        explanation.layout().addWidget(QLabel("Total Vessel ROB = all fuel remaining onboard.\n\nBunker Tanks ROB = fuel remaining in configured bunker/storage tanks.\n\nMax Lift = selected physical tank space, converted with incoming density and VCF."))
        summary_row.addWidget(explanation, 2)
        layout.addLayout(summary_row)

        # BUNKER PLAN
        planning_panel = QFrame()
        planning_panel.setObjectName("panel")
        planning_layout = QVBoxLayout(planning_panel)
        planning_layout.setContentsMargins(16, 14, 16, 14)
        planning_layout.setSpacing(10)

        planning_header = QHBoxLayout()

        planning_title = QLabel("BUNKER PLAN")
        planning_title.setObjectName("sectionTitle")
        planning_header.addWidget(planning_title)

        planning_header.addStretch()

        capacity_button = QPushButton("Capacity Settings")
        capacity_button.clicked.connect(self._open_capacity_settings)
        planning_header.addWidget(capacity_button)

        planning_layout.addLayout(planning_header)

        # Reuse all existing bunker-plan widgets and service wiring.
        planning_layout.addWidget(self.plan_panel)
        layout.addWidget(planning_panel)

        # PORT CONSUMPTION
        consumption_panel = QFrame()
        consumption_panel.setObjectName("panel")
        consumption_layout = QGridLayout(consumption_panel)
        consumption_layout.setContentsMargins(16, 14, 16, 14)
        consumption_layout.setHorizontalSpacing(24)
        consumption_layout.setVerticalSpacing(8)

        consumption_title = QLabel("PORT CONSUMPTION")
        consumption_title.setObjectName("sectionTitle")
        consumption_layout.addWidget(consumption_title, 0, 0, 1, 2)

        consumption_layout.addWidget(QLabel("Calculated"), 1, 0)
        consumption_layout.addWidget(
            QLabel(_format_fuels(row.port_consumption_mt)),
            1,
            1,
        )

        layout.addWidget(consumption_panel)

        # DEPARTURE
        departure_panel = QFrame()
        departure_panel.setObjectName("panel")
        departure_layout = QGridLayout(departure_panel)
        departure_layout.setContentsMargins(16, 14, 16, 14)
        departure_layout.setHorizontalSpacing(24)
        departure_layout.setVerticalSpacing(8)

        departure_title = QLabel("DEPARTURE")
        departure_title.setObjectName("sectionTitle")
        departure_layout.addWidget(departure_title, 0, 0, 1, 2)

        departure_layout.addWidget(QLabel("Predicted Departure ROB"), 1, 0)
        departure_layout.addWidget(
            QLabel(_format_fuels(row.departure_rob_mt)),
            1,
            1,
        )

        layout.addWidget(departure_panel)

        layout.addStretch()

        close_row = QHBoxLayout()
        close_row.addStretch()

        close = QPushButton("Close")
        close.setFixedWidth(120)
        close.clicked.connect(details.accept)
        close_row.addWidget(close)

        dialog_layout.addLayout(close_row)

        details.exec()

        # Return reusable planner controls to their neutral parent.
        self.plan_panel.setParent(self.content)

    def _open_capacity_settings(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Vessel Fuel Capacity Settings")
        dialog.resize(620, 360)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        layout.addWidget(self.capacity_panel)

        close_row = QHBoxLayout()
        close_row.addStretch()

        close = QPushButton("Close")
        close.setFixedWidth(120)
        close.clicked.connect(dialog.accept)
        close_row.addWidget(close)

        layout.addLayout(close_row)

        dialog.exec()

        self.capacity_panel.setParent(self.content)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in [self.event_combo, self.save_capacity_button, self.save_plan_button, self.confirm_plan_button, self.use_max_button, self.clear_plan_button]:
            widget.setEnabled(enabled)
        for inputs in (self._capacity_inputs, self._target_inputs, self._planned_inputs):
            for spinbox in inputs.values():
                spinbox.setEnabled(enabled)


def _spinbox(suffix: str, minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
    spinbox = QDoubleSpinBox()
    spinbox.setDecimals(2)
    spinbox.setRange(minimum, maximum)
    spinbox.setSingleStep(step)
    spinbox.setSuffix(suffix)
    return spinbox


def _detail_card(title: str) -> QFrame:
    card = QFrame()
    card.setObjectName("panel")
    card.setMinimumHeight(136)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(8)
    heading = QLabel(title)
    heading.setObjectName("fieldLabel")
    layout.addWidget(heading)
    return card


def _format_fuels(values: dict[str, float | None], *, zero_blank: bool = False) -> str:
    parts = []
    for short, fuel in (("U", "ULSFO"), ("V", "VLSFO"), ("M", "MDO")):
        value = values.get(fuel)
        if zero_blank and value == 0:
            continue
        parts.append(f"{short} {'—' if value is None else f'{float(value):.1f}'}")
    return " / ".join(parts) if parts else "—"


def _utc_instant(value: datetime) -> datetime:
    """Treat legacy naïve Actual ROB timestamps as UTC for safe instant comparison."""
    return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _format_mt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f} MT"
