from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QAbstractTableModel, Qt, Signal
from PySide6.QtGui import QColor
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
        super().__init__(parent); self._service, self._plan = service, plan; self.setWindowTitle("Receiving Tanks"); self.resize(900, 520)
        layout = QVBoxLayout(self); layout.addWidget(QLabel("Projected arrival uses the bunker event arrival UTC. Typing a value creates a manual override."))
        self.table = QTableWidget(0, 8); self.table.setHorizontalHeaderLabels(("Selected", "Tank", "Capacity m3", "Latest Actual m3", "Projected Arrival m3", "Source", "Target Fill %", "Available m3")); self.table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.table)
        incoming = QFormLayout(); self.batch_input = QComboBox(); self.batch_input.addItem("No incoming batch", None)
        for batch in service.list_fuel_batches(plan.vessel_id): self.batch_input.addItem(f"{batch.batch_name} ({batch.fuel_type})", batch.id)
        self.fuel_label = QLabel("--"); self.density_label = QLabel("--"); self.vcf_input = QLineEdit(); self.vcf_input.setPlaceholderText("Manual VCF, e.g. 0.98500")
        incoming.addRow("Incoming Batch", self.batch_input); incoming.addRow("Fuel Type", self.fuel_label); incoming.addRow("Density @15 C", self.density_label); incoming.addRow("Manual VCF", self.vcf_input); layout.addLayout(incoming); layout.addWidget(QLabel("VCF is entered manually. Automatic ASTM/API calculation is not enabled."))
        self.summary_label = QLabel("Selected Tanks: 0 | Available Volume: -- | Tank-Based Max Lift: --"); layout.addWidget(self.summary_label)
        actions = QHBoxLayout(); self.use_latest_button = QPushButton("Use Latest Actual"); self.use_latest_button.clicked.connect(self._use_latest); actions.addWidget(self.use_latest_button); self.use_estimate_button = QPushButton("Use Estimate"); self.use_estimate_button.clicked.connect(self._use_estimate); actions.addWidget(self.use_estimate_button); actions.addStretch(); layout.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel); buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save Receiving Plan"); buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        persisted = {row.tank_id: row for row in service.list_receiving_tank_plan(plan)}; snapshot = service.load_incoming_fuel_snapshot(plan)
        if snapshot.fuel_batch_id is not None: self.batch_input.setCurrentIndex(next((i for i in range(self.batch_input.count()) if self.batch_input.itemData(i) == snapshot.fuel_batch_id), 0))
        if snapshot.manual_vcf is not None: self.vcf_input.setText(f"{snapshot.manual_vcf:.5f}")
        candidates = [BunkerReceivingTankPlan(tank.id, persisted[tank.id].projected_arrival_volume_m3 if tank.id in persisted else None, persisted[tank.id].target_fill_percent if tank.id in persisted else default_target) for tank, _latest in service.list_eligible_receiving_tanks(plan.vessel_id)]
        estimates = service.resolve_receiving_tank_arrivals(plan, candidates)
        for row, (tank, latest) in enumerate(service.list_eligible_receiving_tanks(plan.vessel_id)):
            saved = persisted.get(tank.id); estimate = estimates[tank.id]; self.table.insertRow(row); check=QCheckBox(); check.setChecked(saved is not None); self.table.setCellWidget(row,0,check); item=QTableWidgetItem(tank.name); item.setData(Qt.ItemDataRole.UserRole,(tank.id,latest,estimate)); self.table.setItem(row,1,item); self.table.setItem(row,2,QTableWidgetItem(f"{tank.capacity_m3:.3f}")); self.table.setItem(row,3,QTableWidgetItem("--" if latest is None else f"{latest:.3f}")); projected=QLineEdit("" if estimate.projected_arrival_volume_m3 is None else f"{estimate.projected_arrival_volume_m3:.3f}"); projected.setProperty("manual_override", saved is not None and saved.projected_arrival_volume_m3 is not None); projected.textEdited.connect(lambda _text, field=projected: field.setProperty("manual_override", True)); target=QDoubleSpinBox(); target.setRange(.01,100); target.setValue(saved.target_fill_percent if saved else default_target); available="--" if estimate.projected_arrival_volume_m3 is None else f"{max(0.0, tank.capacity_m3 * target.value() / 100 - estimate.projected_arrival_volume_m3):.3f}"; self.table.setCellWidget(row,4,projected); source=QTableWidgetItem("Manual" if estimate.source == "MANUAL" else "Estimated" if estimate.source == "ESTIMATED" else "Unavailable"); source.setToolTip(estimate.issue or ""); self.table.setItem(row,5,source); self.table.setCellWidget(row,6,target); self.table.setItem(row,7,QTableWidgetItem(available))
        self.batch_input.currentIndexChanged.connect(self._batch_changed); self._batch_changed()

    def _batch_changed(self):
        batch_id=self.batch_input.currentData(); batch=next((b for b in self._service.list_fuel_batches(self._plan.vessel_id) if b.id==batch_id),None); self.fuel_label.setText(batch.fuel_type if batch else "--"); self.density_label.setText(f"{batch.density_15_kg_m3:.3f} kg/m3" if batch else "--")

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

    def _save(self):
        rows=[]
        for row in range(self.table.rowCount()):
            if not self.table.cellWidget(row,0).isChecked(): continue
            tank_id,_,_=self.table.item(row,1).data(Qt.ItemDataRole.UserRole); field=self.table.cellWidget(row,4); text=field.text().strip()
            rows.append(BunkerReceivingTankPlan(tank_id, float(text) if field.property("manual_override") and text else None, self.table.cellWidget(row,6).value()))
        try: self._service.save_receiving_tank_plan(self._plan, rows, self.batch_input.currentData(), float(self.vcf_input.text()) if self.vcf_input.text().strip() else None)
        except (ValueError, TypeError) as error: QMessageBox.warning(self,"Receiving plan not saved",str(error)); return
        self.accept()


class BunkerDistributionDialog(QDialog):
    def __init__(self, service: BunkerService, plan, parent=None):
        super().__init__(parent); self._service, self._plan = service, plan; self.setWindowTitle("Bunker Distribution"); self.resize(620, 360)
        layout = QVBoxLayout(self); self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(("Tank", "Available Capacity MT", "Receipt MT")); layout.addWidget(self.table)
        incoming = service.load_incoming_fuel_snapshot(plan); batch = next((item for item in service.list_fuel_batches(plan.vessel_id) if item.id == incoming.fuel_batch_id), None)
        self._fuel = batch.fuel_type if batch else None; self._total = plan.quantity_for(self._fuel) if self._fuel else 0.0
        rows = service.list_receiving_tank_plan(plan); tanks = {tank.id: tank for tank, _ in service.list_eligible_receiving_tanks(plan.vessel_id)}; projections = service.resolve_receiving_tank_arrivals(plan); saved = {item.tank_id: item for item in service.list_tank_receipts(plan)}
        for index, row in enumerate(rows):
            tank = tanks.get(row.tank_id); projection = projections.get(row.tank_id)
            if tank is None or projection is None or projection.projected_arrival_volume_m3 is None or incoming.density_15_kg_m3 is None or incoming.manual_vcf is None: capacity = None
            else:
                from fuel_consumption_calculator.calculations.tank_max_lift import SelectedReceivingTank, calculate_tank_max_lift
                capacity = calculate_tank_max_lift([SelectedReceivingTank(tank.id, tank.capacity_m3, projection.projected_arrival_volume_m3, row.target_fill_percent)], incoming_density_15_kg_m3=incoming.density_15_kg_m3, incoming_manual_vcf=incoming.manual_vcf).total_max_lift_mt
            self.table.insertRow(index); item=QTableWidgetItem(tank.name if tank else str(row.tank_id)); item.setData(Qt.ItemDataRole.UserRole, row.tank_id); self.table.setItem(index,0,item); self.table.setItem(index,1,QTableWidgetItem("--" if capacity is None else f"{capacity:.3f}")); value=QDoubleSpinBox(); value.setRange(0, capacity if capacity is not None else 999999.99); value.setDecimals(3); value.setValue(saved[row.tank_id].quantity_mt if row.tank_id in saved else 0); value.valueChanged.connect(self._update); self.table.setCellWidget(index,2,value)
        self.summary=QLabel(); layout.addWidget(self.summary); buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject); layout.addWidget(buttons); self._update()

    def _update(self):
        allocated=sum(self.table.cellWidget(row,2).value() for row in range(self.table.rowCount())); self.summary.setText(f"Aggregate Bunker: {self._total:.3f} MT   Allocated: {allocated:.3f} MT   Remaining: {self._total-allocated:.3f} MT")

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
            title = QLabel(fuel_type)
            title.setObjectName("sectionTitle")
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
        latest = max(observations, key=lambda item: item.effective_at_utc, default=None)
        if latest is None:
            self.actual_sounding_label.setText("No Actual Sounding ROB recorded")
        else:
            quantities = " | ".join(f"{fuel} {latest.quantities_mt.get(fuel):.2f} MT" for fuel in FUEL_TYPES)
            remarks = f" | {latest.remarks}" if latest.remarks else ""
            self.actual_sounding_label.setText(f"Effective: {latest.effective_at_utc:%d %b %Y %H:%M UTC} | {quantities}{remarks}")
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
        latest = max(observations, key=lambda item: item.effective_at_utc, default=None)
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
            self._planned_inputs[fuel_type].setValue(limit.max_lift_mt)

    def _open_receiving_tanks(self) -> None:
        vessel=self._vessel_service.get_active_vessel(); event=self._selected_event()
        if vessel is None or event is None: return
        plan=self._bunker_service.build_plan(vessel_id=vessel.id,event=event,quantities={fuel: self._planned_inputs[fuel].value() for fuel in FUEL_TYPES})
        default_target=next(iter(self._target_inputs.values())).value() if self._target_inputs else 90
        if ReceivingTanksDialog(self._bunker_service,plan,default_target,self).exec() == QDialog.DialogCode.Accepted:
            self._refresh_projection(vessel.id); self._selection_changed(); self.status_label.setText("Receiving tank plan saved as DRAFT.")

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
        tank_result = self._bunker_service.tank_based_max_lift(plan) if tank_plan else None
        if tank_plan:
            rows = self._bunker_service.list_receiving_tank_plan(plan)
            if tank_result is None or tank_result.total_max_lift_mt is None:
                self.receiving_summary_label.setText(f"{len(rows)} tanks selected · Max Lift incomplete")
                self._lift_limits = {fuel: replace(limit, max_lift_mt=None) for fuel, limit in self._lift_limits.items()}
            else:
                self.receiving_summary_label.setText(f"{len(rows)} tanks selected · {tank_result.total_available_volume_m3:.3f} m3 available")
                snapshot = self._bunker_service.load_incoming_fuel_snapshot(plan)
                batch = next((b for b in self._bunker_service.list_fuel_batches(plan.vessel_id) if b.id == snapshot.fuel_batch_id), None)
                self._lift_limits = {fuel: replace(limit, max_lift_mt=tank_result.total_max_lift_mt if batch and fuel == batch.fuel_type else 0.0) for fuel, limit in self._lift_limits.items()}
                if sum(self._planned_inputs[fuel].value() for fuel in FUEL_TYPES) > tank_result.total_max_lift_mt + 0.001:
                    self.receiving_summary_label.setText("Receiving plan issue: Planned Lift exceeds refreshed Max Lift")
        else:
            self.receiving_summary_label.setText("Receiving tanks not configured")
        for fuel_type, limit in self._lift_limits.items():
            getattr(self, f"_{fuel_type.lower()}_capacity_label").setText(_format_mt(limit.capacity_mt))
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

        # ARRIVAL
        arrival_panel = QFrame()
        arrival_panel.setObjectName("panel")
        arrival_layout = QGridLayout(arrival_panel)
        arrival_layout.setContentsMargins(16, 14, 16, 14)
        arrival_layout.setHorizontalSpacing(24)
        arrival_layout.setVerticalSpacing(8)

        arrival_title = QLabel("ARRIVAL")
        arrival_title.setObjectName("sectionTitle")
        arrival_layout.addWidget(arrival_title, 0, 0, 1, 2)

        arrival_layout.addWidget(QLabel("Arrival ROB"), 1, 0)
        arrival_layout.addWidget(
            QLabel(_format_fuels(row.arrival_rob_mt)),
            1,
            1,
        )

        arrival_layout.addWidget(QLabel("ROB Source"), 2, 0)
        arrival_layout.addWidget(QLabel(row.rob_source), 2, 1)

        layout.addWidget(arrival_panel)

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


def _format_fuels(values: dict[str, float | None], *, zero_blank: bool = False) -> str:
    parts = []
    for short, fuel in (("U", "ULSFO"), ("V", "VLSFO"), ("M", "MDO")):
        value = values.get(fuel)
        if zero_blank and value == 0:
            continue
        parts.append(f"{short} {'—' if value is None else f'{float(value):.1f}'}")
    return " / ".join(parts) if parts else "—"


def _format_mt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f} MT"
