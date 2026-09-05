from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone

from PySide6.QtCore import QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QHeaderView, QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from fuel_consumption_calculator.domain.fuel_tank import (
    FUEL_BATCH_TYPES,
    FUEL_TANK_TYPES,
    MEASUREMENT_TYPES,
    FuelBatch,
    FuelTank,
    InternalFuelTransfer,
    TankSounding,
)
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService, FuelTankValidationError
from fuel_consumption_calculator.services.tank_forecast_service import TankForecastService
from fuel_consumption_calculator.domain.voyage import ActualROBObservation
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader
from fuel_consumption_calculator.ui.widgets.fuel_display import FUEL_COLORS, FuelBadge, fuel_color
from fuel_consumption_calculator.ui.pages.fuel_tank_operational_dialogs import CalibrationDialog, UpdateTankROBDialog
from fuel_consumption_calculator.domain.tank_forecast import TankConsumptionPlan, TankConsumptionPlanPhase, TankConsumptionPlanPhaseTank


NEUTRAL_LEVEL_COLOR = "#477a91"
MDO_SLOTS = ("MDO_1_SERV", "MDO_2_SERV", "MDO_1_STOR", "MDO_2_STOR")
SUPPORT_SLOTS = ("ULSFO_SETT", "ULSFO_SERV", "HFO_SERV", "HFO_SETT", "OVFLW_ER")
DEEP_SLOTS = ("DEEP_3P", "DEEP_2P", "DEEP_1P", "DEEP_3S", "DEEP_2S", "DEEP_1S")
VESSEL_TANK_SET = (
    ("HFO DEEP TK 3P", "BUNKER", True), ("HFO DEEP TK 2P", "BUNKER", True), ("HFO DEEP TK 1P", "BUNKER", True), ("LSFO DEEP TK 3S", "BUNKER", True), ("HFO DEEP TK 2S", "BUNKER", True), ("HFO DEEP TK 1S", "BUNKER", True), ("NO.1 DO STOR.TK", "BUNKER", True), ("NO.2 DO STOR.TK", "BUNKER", True), ("HFO SETT.TK", "SETTLING", False), ("LSHFO SETT.TK", "SETTLING", False), ("HFO SERV.TK", "SERVICE", False), ("LSHFO SERV.TK", "SERVICE", False), ("NO.1 DO SERV.TK", "SERVICE", False), ("NO.2 DO SERV.TK", "SERVICE", False), ("OVFLW TK CH", "OTHER", False), ("OVFLW TK ER", "OTHER", False),
)
VESSEL_TANK_CAPACITIES = {"HFO DEEP TK 1P":1515.4,"HFO DEEP TK 1S":1573.3,"HFO DEEP TK 2P":1643.5,"HFO DEEP TK 2S":1643.5,"HFO DEEP TK 3P":849.2,"LSFO DEEP TK 3S":849.2,"HFO SERV.TK":154.9,"HFO SETT.TK":294.3,"LSHFO SERV.TK":154.9,"LSHFO SETT.TK":158.6,"NO.1 DO STOR.TK":182.0,"NO.2 DO STOR.TK":151.7,"NO.1 DO SERV.TK":196.8,"NO.2 DO SERV.TK":182.0,"OVFLW TK ER":78.6,"OVFLW TK CH":62.1}


class TankLevelWidget(QWidget):
    def __init__(self, fill_percent: float | None, fuel_type: str | None, width: int, height: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._unknown = fill_percent is None
        self._fill_percent = 0.0 if fill_percent is None else max(0.0, min(100.0, fill_percent))
        self._color = QColor(fuel_color(fuel_type or "UNKNOWN") if fuel_type else NEUTRAL_LEVEL_COLOR)
        self.setFixedSize(width, height)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outline = self.rect().adjusted(2, 2, -2, -2)
        painter.setPen(QColor("#5c8194"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(outline, 4, 4)
        if self._unknown: return
        height = round(outline.height() * self._fill_percent / 100)
        if height:
            liquid = outline.adjusted(2, outline.height() - height + 2, -2, -2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color)
            painter.drawRect(liquid)


class TankCard(QFrame):
    selected = Signal(int)
    activated = Signal(int)

    def __init__(self, tank: FuelTank, fuel_type: str | None, batch_name: str | None, latest: TankSounding | None, kind: str = "other", parent: QWidget | None = None, consumption_status: str | None = None) -> None:
        super().__init__(parent)
        self._tank_id = tank.id
        self.setObjectName("tankCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.kind = kind; self.setMinimumHeight(180); self.setProperty("fuel", (fuel_type or "UNASSIGNED").upper())
        self.setToolTip(tank.name)
        fill_percent = None if latest is None else latest.calculated_volume_m3 / tank.capacity_m3 * 100
        layout = QHBoxLayout(self); layout.setContentsMargins(17, 16, 16, 16); layout.setSpacing(14)
        details = QVBoxLayout()
        details.setSpacing(5)
        name = QLabel(_short_display_name(tank.name)); name.setObjectName("tankName")
        marker = FuelBadge(fuel_type or "UNASSIGNED")
        top = QHBoxLayout(); top.setContentsMargins(0, 0, 0, 0); top.addWidget(name, 1); top.addWidget(marker); details.addLayout(top)
        if latest is None:
            details.addWidget(_card_value("—")); details.addWidget(_card_meta("No ROB available")); details.addWidget(_card_meta("FILL  —"))
        else:
            if latest.calculated_mass_mt is not None:
                details.addWidget(_card_value(f"{latest.calculated_mass_mt:.2f} MT"))
            else:
                details.addWidget(_card_value("—"))
            details.addWidget(_card_meta("ACTUAL ROB")); percent = QLabel(f"{max(0.0, min(100.0, fill_percent or 0.0)):.0f}%"); percent.setObjectName("tankFill"); percent.setStyleSheet(f"color:{fuel_color(fuel_type or 'UNKNOWN')};"); details.addWidget(percent)
        if consumption_status:
            status = _card_meta(consumption_status); status.setWordWrap(True); details.addWidget(status)
        details.addStretch()
        layout.addLayout(details, 1)
        gauge_box = QVBoxLayout(); gauge_box.setContentsMargins(0, 0, 0, 0); gauge_box.setSpacing(0)
        for mark in ("100%", "75%", "50%", "25%", "0%"):
            label = QLabel(mark); label.setObjectName("tankGaugeMark"); gauge_box.addWidget(label, 1)
        gauge = TankLevelWidget(fill_percent, fuel_type, 20, 126)
        gauge_wrap = QHBoxLayout(); gauge_wrap.setContentsMargins(0, 0, 0, 0); gauge_wrap.setSpacing(9); gauge_wrap.addWidget(gauge); gauge_wrap.addLayout(gauge_box); layout.addLayout(gauge_wrap)

    def set_selected(self, selected: bool) -> None:
        self.setStyleSheet("QFrame#tankCard { border: 2px solid #2ba2c3; }" if selected else "")

    def mousePressEvent(self, event) -> None:
        if self._tank_id is not None:
            self.selected.emit(self._tank_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        super().mouseDoubleClickEvent(event)
        if self._tank_id is not None:
            self.activated.emit(self._tank_id)


class TankDialog(QDialog):
    def __init__(self, service: FuelTankService, vessel_id: int, tank: FuelTank | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service, self._vessel_id, self._tank = service, vessel_id, tank
        self.setWindowTitle("Add Fuel Tank" if tank is None else "Edit Fuel Tank")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_input = QLineEdit(tank.name if tank else "")
        self.type_input = QComboBox(); self.type_input.addItems(FUEL_TANK_TYPES); self.type_input.setCurrentText(tank.tank_type if tank else "BUNKER")
        self.capacity_input = QDoubleSpinBox(); self.capacity_input.setRange(0.01, 100000.0); self.capacity_input.setDecimals(2); self.capacity_input.setSuffix(" m³"); self.capacity_input.setValue(tank.capacity_m3 if tank else 1.0)
        self.receiving_input = QCheckBox(); self.receiving_input.setChecked(tank.bunker_receiving_eligible if tank else False)
        self.active_input = QCheckBox(); self.active_input.setChecked(tank.is_active if tank else True)
        self.notes_input = QLineEdit(tank.notes or "" if tank else "")
        form.addRow("Tank Name", self.name_input); form.addRow("Tank Type", self.type_input); form.addRow("Capacity", self.capacity_input)
        form.addRow("Bunker Receiving Eligible", self.receiving_input); form.addRow("Active", self.active_input); form.addRow("Notes", self.notes_input)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def _save(self) -> None:
        tank = FuelTank(
            id=self._tank.id if self._tank else None, vessel_id=self._vessel_id, name=self.name_input.text().strip(),
            tank_type=self.type_input.currentText(), capacity_m3=self.capacity_input.value(),
            preferred_measurement_type=self._tank.preferred_measurement_type if self._tank else "SOUNDING",
            bunker_receiving_eligible=self.receiving_input.isChecked(), is_active=self.active_input.isChecked(),
            current_fuel_batch_id=self._tank.current_fuel_batch_id if self._tank else None, notes=self.notes_input.text().strip() or None,
        )
        try:
            (self._service.create_tank if self._tank is None else self._service.update_tank)(tank)
        except ValueError as error:
            QMessageBox.warning(self, "Tank not saved", str(error)); return
        self.accept()


class VesselTankSetDialog(QDialog):
    """Confirmation-based setup for this vessel's known physical tank set."""

    def __init__(self, service: FuelTankService, vessel_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service, self._vessel_id = service, vessel_id
        self.setWindowTitle("Load Vessel Tank Set")
        self.setMinimumSize(720, 510)
        layout = QVBoxLayout(self)
        layout.addWidget(_muted("Verified 100% physical capacities are prefilled; adjust only if the vessel placard differs."))
        self.tank_table = QTableWidget(len(VESSEL_TANK_SET), 5)
        self.tank_table.setHorizontalHeaderLabels(("Include", "Tank Name", "Tank Type", "Capacity m³", "Bunker Receiving"))
        self.tank_table.verticalHeader().setVisible(False)
        self.tank_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tank_table.horizontalHeader().setStretchLastSection(True)
        self.row_controls: list[tuple[QCheckBox, QDoubleSpinBox, QCheckBox]] = []
        for row, (name, tank_type, receiving_default) in enumerate(VESSEL_TANK_SET):
            include = QCheckBox(); include.setChecked(True)
            capacity = QDoubleSpinBox(); capacity.setRange(0.0, 100000.0); capacity.setDecimals(2); capacity.setSuffix(" m³"); capacity.setSpecialValueText("Required"); capacity.setValue(VESSEL_TANK_CAPACITIES[name])
            receiving = QCheckBox(); receiving.setChecked(receiving_default)
            self.tank_table.setCellWidget(row, 0, include)
            self.tank_table.setItem(row, 1, QTableWidgetItem(name))
            self.tank_table.setItem(row, 2, QTableWidgetItem(tank_type))
            self.tank_table.setCellWidget(row, 3, capacity)
            self.tank_table.setCellWidget(row, 4, receiving)
            self.row_controls.append((include, capacity, receiving))
        self.tank_table.resizeColumnsToContents()
        layout.addWidget(self.tank_table)
        self.summary_label = _muted("")
        layout.addWidget(self.summary_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.create_button = QPushButton("Create Selected Tanks")
        self.create_button.setObjectName("primaryButton")
        self.create_button.clicked.connect(self._create_selected)
        buttons.addButton(self.create_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def create_selected_tanks(self) -> tuple[int, int, int]:
        selected: list[tuple[str, str, bool, float]] = []
        missing_capacities: list[str] = []
        for row, (name, tank_type, _) in enumerate(VESSEL_TANK_SET):
            include, capacity, receiving = self.row_controls[row]
            if not include.isChecked():
                continue
            if capacity.value() <= 0:
                missing_capacities.append(name)
            else:
                selected.append((name, tank_type, receiving.isChecked(), capacity.value()))
        if missing_capacities:
            raise ValueError("Enter a capacity greater than 0 m³ for every selected tank: " + ", ".join(missing_capacities))
        existing_tanks = self._service.list_tanks(self._vessel_id, include_inactive=True)
        existing_names = {_normalized_name(tank.name): tank for tank in existing_tanks}
        existing_positions = {_position_for_tank(tank.name): tank for tank in existing_tanks}
        created = updated = unchanged = 0
        for name, tank_type, receiving, capacity in selected:
            position = _position_for_tank(name)
            existing = existing_names.get(_normalized_name(name)) or (existing_positions.get(position) if position is not None else None)
            if existing is not None:
                configured = replace(
                    existing,
                    tank_type=tank_type,
                    capacity_m3=capacity,
                    bunker_receiving_eligible=receiving,
                )
                if configured != existing:
                    self._service.update_tank(configured)
                    updated += 1
                else:
                    unchanged += 1
                continue
            saved = self._service.create_tank(FuelTank(
                id=None, vessel_id=self._vessel_id, name=name, tank_type=tank_type, capacity_m3=capacity,
                preferred_measurement_type="SOUNDING", bunker_receiving_eligible=receiving,
            ))
            existing_names[_normalized_name(saved.name)] = saved
            existing_positions[_position_for_tank(saved.name)] = saved
            created += 1
        return created, updated, unchanged

    def _create_selected(self) -> None:
        try:
            created, updated, unchanged = self.create_selected_tanks()
        except ValueError as error:
            QMessageBox.warning(self, "Tank set not created", str(error))
            return
        self.summary_label.setText(
            f"Created: {created}   Updated: {updated}   Unchanged: {unchanged}"
        )


class LegacyTankDetailsDialog(QDialog):
    def __init__(self, service: FuelTankService, tank: FuelTank, fuel_type: str | None, batch_name: str | None, latest: TankSounding | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tank Details")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tank.name, objectName="pageTitle"))
        form = QFormLayout()
        values = (
            ("Tank Type", tank.tank_type), ("Capacity", f"{tank.capacity_m3:.2f} m³"), ("Active", "Yes" if tank.is_active else "No"),
            ("Bunker Receiving", "Yes" if tank.bunker_receiving_eligible else "No"), ("Current Fuel", fuel_type or "UNKNOWN"),
            ("Current Batch", batch_name or "No batch assigned"), ("Latest Volume", f"{latest.calculated_volume_m3:.2f} m³" if latest else "No sounding"),
            ("Latest MT", f"{latest.calculated_mass_mt:.2f} MT" if latest and latest.calculated_mass_mt is not None else "—"),
            ("Fill", f"{max(0.0, min(100.0, latest.calculated_volume_m3 / tank.capacity_m3 * 100)):.1f}%" if latest else "—"),
            ("Latest Sounding", _format_utc(latest.effective_at_utc) if latest else "No sounding"),
        )
        for label, value in values:
            form.addRow(label, QLabel(value))
        layout.addLayout(form)
        future = QHBoxLayout()
        update = QPushButton("Update ROB"); update.clicked.connect(lambda: UpdateTankROBDialog(service, tank, self).exec())
        calibration = QPushButton("Calibration"); calibration.clicked.connect(lambda: CalibrationDialog(service, tank, self).exec())
        batch = QPushButton("Fuel / Batch Details (Coming next)"); batch.setEnabled(False)
        for button in (update, calibration, batch): future.addWidget(button)
        layout.addLayout(future)
        close_button = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); close_button.rejected.connect(self.reject); layout.addWidget(close_button)


class FuelBatchDialog(QDialog):
    """Reusable editor for vessel-level fuel batch details."""

    def __init__(self, service: FuelTankService, vessel_id: int, batch: FuelBatch | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service, self._vessel_id, self._batch = service, vessel_id, batch
        self.setWindowTitle("Create Fuel Batch" if batch is None else "Edit Fuel Batch")
        self.setMinimumWidth(410)
        layout = QVBoxLayout(self); form = QFormLayout()
        self.batch_name_input = QLineEdit(batch.batch_name if batch else "")
        self.fuel_type_input = QComboBox(); self.fuel_type_input.addItems(FUEL_BATCH_TYPES); self.fuel_type_input.setCurrentText(batch.fuel_type if batch else "VLSFO")
        self.density_input = QDoubleSpinBox(); self.density_input.setRange(0.01, 2000); self.density_input.setDecimals(3); self.density_input.setSuffix(" kg/m3"); self.density_input.setValue(batch.density_15_kg_m3 if batch else 1)
        self.sulfur_input = QLineEdit(_optional_number(batch.sulfur_percent) if batch else "")
        self.viscosity_input = QLineEdit(_optional_number(batch.viscosity_50_cst) if batch else "")
        self.flash_point_input = QLineEdit(_optional_number(batch.flash_point_c) if batch else "")
        self.pour_point_input = QLineEdit(_optional_number(batch.pour_point_c) if batch else "")
        self.water_input = QLineEdit(_optional_number(batch.water_percent) if batch else "")
        self.lab_reference_input = QLineEdit(batch.lab_reference or "" if batch else "")
        self.bunker_port_input = QLineEdit(batch.bunker_port or "" if batch else "")
        self.bunker_date_input = QLineEdit(batch.bunker_date or "" if batch else "")
        self.remarks_input = QLineEdit(batch.remarks or "" if batch else "")
        for label, widget in (
            ("Batch Name", self.batch_name_input), ("Fuel Type", self.fuel_type_input),
            ("Density @15°C (kg/m³)", self.density_input), ("Sulfur %", self.sulfur_input),
            ("Viscosity @50 C cSt", self.viscosity_input), ("Flash Point C", self.flash_point_input),
            ("Pour Point C", self.pour_point_input), ("Water %", self.water_input),
            ("Lab Reference", self.lab_reference_input), ("Bunker Port", self.bunker_port_input),
            ("Bunker Date", self.bunker_date_input), ("Remarks", self.remarks_input),
        ):
            form.addRow(label, widget)
        layout.addLayout(form)
        layout.addWidget(_muted("Example: 978 kg/m³, not 0.978."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def _save(self) -> None:
        try:
            if self.density_input.value() < 100:
                raise ValueError(
                    "Density must be entered in kg/m³ (for example 978, not 0.978)."
                )
            batch = FuelBatch(
                id=self._batch.id if self._batch else None, vessel_id=self._vessel_id,
                batch_name=self.batch_name_input.text(), fuel_type=self.fuel_type_input.currentText(), density_15_kg_m3=self.density_input.value(),
                sulfur_percent=_optional_float(self.sulfur_input.text(), "Sulfur percent"), viscosity_50_cst=_optional_float(self.viscosity_input.text(), "Viscosity"),
                flash_point_c=_optional_float(self.flash_point_input.text(), "Flash point"), pour_point_c=_optional_float(self.pour_point_input.text(), "Pour point"),
                water_percent=_optional_float(self.water_input.text(), "Water percent"), lab_reference=self.lab_reference_input.text().strip() or None,
                bunker_port=self.bunker_port_input.text().strip() or None, bunker_date=self.bunker_date_input.text().strip() or None, remarks=self.remarks_input.text().strip() or None,
            )
            (self._service.create_fuel_batch if self._batch is None else self._service.update_fuel_batch)(batch)
        except ValueError as error:
            QMessageBox.warning(self, "Fuel batch not saved", str(error)); return
        self.accept()


class TankFuelBatchDialog(QDialog):
    def __init__(self, service: FuelTankService, tank: FuelTank, on_changed=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service, self._tank_id, self._vessel_id, self._on_changed = service, tank.id, tank.vessel_id, on_changed
        self.setWindowTitle("Fuel / Batch Details"); self.setMinimumSize(510, 350)
        layout = QVBoxLayout(self); self.tank_label = QLabel(objectName="pageTitle"); layout.addWidget(self.tank_label)
        self.current_fuel_label = QLabel(); self.current_batch_label = QLabel(); self.density_label = QLabel()
        current = QFormLayout(); current.addRow("Current Fuel", self.current_fuel_label); current.addRow("Current Batch", self.current_batch_label); current.addRow("Density @15 C", self.density_label); layout.addLayout(current)
        layout.addWidget(_section("VESSEL FUEL BATCHES"))
        self.batch_table = QTableWidget(0, 3); self.batch_table.setHorizontalHeaderLabels(("Batch Name", "Fuel Type", "Density @15 C")); self.batch_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.batch_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection); self.batch_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.batch_table.horizontalHeader().setStretchLastSection(True); self.batch_table.itemSelectionChanged.connect(self._update_buttons); layout.addWidget(self.batch_table)
        actions = QHBoxLayout()
        self.create_button = QPushButton("Create New"); self.create_button.clicked.connect(self._create)
        self.edit_button = QPushButton("Edit Selected"); self.edit_button.clicked.connect(self._edit)
        self.assign_button = QPushButton("Assign to Tank"); self.assign_button.setObjectName("primaryButton"); self.assign_button.clicked.connect(self._assign)
        self.clear_button = QPushButton("Clear Assignment"); self.clear_button.clicked.connect(self._clear)
        for button in (self.create_button, self.edit_button, self.assign_button, self.clear_button): actions.addWidget(button)
        actions.addStretch(); layout.addLayout(actions)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); close.rejected.connect(self.reject); layout.addWidget(close)
        self.refresh()

    def refresh(self) -> None:
        tank = self._service.get_tank(self._tank_id)
        if tank is None: self.reject(); return
        batch = self._service.get_fuel_batch(tank.current_fuel_batch_id) if tank.current_fuel_batch_id else None
        self.tank_label.setText(f"Tank: {tank.name}"); self.current_fuel_label.setText(batch.fuel_type if batch else "UNKNOWN"); self.current_batch_label.setText(batch.batch_name if batch else "No batch assigned"); self.density_label.setText(f"{batch.density_15_kg_m3:g} kg/m3" if batch else "--")
        selected_id = self.selected_batch_id(); self.batch_table.setRowCount(0)
        for row, item in enumerate(self._service.list_fuel_batches(self._vessel_id)):
            self.batch_table.insertRow(row)
            name = QTableWidgetItem(item.batch_name); name.setData(Qt.ItemDataRole.UserRole, item.id)
            self.batch_table.setItem(row, 0, name); self.batch_table.setItem(row, 1, QTableWidgetItem(item.fuel_type)); self.batch_table.setItem(row, 2, QTableWidgetItem(f"{item.density_15_kg_m3:g} kg/m3"))
            if item.id == selected_id: self.batch_table.selectRow(row)
        self._update_buttons()

    def selected_batch_id(self) -> int | None:
        selected = self.batch_table.selectedItems()
        return selected[0].data(Qt.ItemDataRole.UserRole) if selected else None

    def _update_buttons(self) -> None:
        selected = self.selected_batch_id() is not None
        self.edit_button.setEnabled(selected); self.assign_button.setEnabled(selected)
        tank = self._service.get_tank(self._tank_id); self.clear_button.setEnabled(bool(tank and tank.current_fuel_batch_id))

    def _create(self) -> None:
        if FuelBatchDialog(self._service, self._vessel_id, parent=self).exec() == QDialog.DialogCode.Accepted: self.refresh(); self._notify_changed()

    def _edit(self) -> None:
        batch_id = self.selected_batch_id(); batch = self._service.get_fuel_batch(batch_id) if batch_id else None
        if batch and FuelBatchDialog(self._service, self._vessel_id, batch, self).exec() == QDialog.DialogCode.Accepted: self.refresh(); self._notify_changed()

    def _assign(self) -> None:
        batch_id = self.selected_batch_id()
        if batch_id is None: return
        try: self._service.assign_fuel_batch_to_tank(self._tank_id, batch_id)
        except ValueError as error: QMessageBox.warning(self, "Fuel batch not assigned", str(error)); return
        self.refresh(); self._notify_changed()

    def _clear(self) -> None:
        if QMessageBox.question(self, "Clear Fuel Batch", "Clear the current fuel batch from this tank?") != QMessageBox.StandardButton.Yes: return
        self._service.clear_fuel_batch_from_tank(self._tank_id); self.refresh(); self._notify_changed()

    def _notify_changed(self) -> None:
        if self._on_changed is not None: self._on_changed()


class TankDetailsDialog(QDialog):
    def __init__(self, service: FuelTankService, tank: FuelTank, fuel_type: str | None, batch_name: str | None, latest: TankSounding | None, parent: QWidget | None = None, on_changed=None, predicted_mass_mt: float | None = None, estimated_empty: str = "--") -> None:
        super().__init__(parent)
        self._service, self._tank_id, self._on_changed = service, tank.id, on_changed
        self.setWindowTitle("Tank Details"); self.setMinimumWidth(380)
        layout = QVBoxLayout(self); layout.addWidget(QLabel(tank.name, objectName="pageTitle")); form = QFormLayout()
        self.current_fuel_value = FuelBadge(fuel_type); self.current_batch_value = QLabel(batch_name or "No batch assigned"); self.density_value = QLabel()
        self._refresh_batch_details(notify=False)
        fill = max(0.0, min(100.0, latest.calculated_volume_m3 / tank.capacity_m3 * 100)) if latest else None
        values = (("Actual ROB", f"{latest.calculated_mass_mt:.2f} MT" if latest and latest.calculated_mass_mt is not None else "--"), ("Estimated ROB", f"{predicted_mass_mt:.2f} MT" if predicted_mass_mt is not None else "--"), ("Estimated Empty", estimated_empty), ("Observed Volume", f"{latest.calculated_volume_m3:.2f} m3" if latest else "--"), ("Fill", f"{fill:.1f}%" if fill is not None else "--"), ("Current Fuel", self.current_fuel_value), ("Fuel Batch", self.current_batch_value), ("Density @15", self.density_value), ("Manual VCF", f"{latest.manual_vcf:.5f}" if latest and latest.manual_vcf is not None else "--"), ("Volume @15", f"{latest.standard_volume_15_m3:.2f} m3" if latest and latest.standard_volume_15_m3 is not None else "--"), ("Measurement / UTC", f"{latest.reading_type} / {_format_utc(latest.effective_at_utc)}" if latest else "--"), ("Tank Type", tank.tank_type), ("Capacity", f"{tank.capacity_m3:.2f} m3"))
        for label, value in values: form.addRow(label, value if isinstance(value, QWidget) else QLabel(value))
        layout.addLayout(form); actions = QHBoxLayout()
        update = QPushButton("Update ROB"); update.clicked.connect(lambda: UpdateTankROBDialog(service, tank, self).exec())
        calibration = QPushButton("Calibration"); calibration.clicked.connect(lambda: CalibrationDialog(service, tank, self).exec())
        batch = QPushButton("Fuel / Batch Details"); batch.clicked.connect(self._open_fuel_batch)
        for button in (update, calibration, batch): actions.addWidget(button)
        layout.addLayout(actions); close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); close.rejected.connect(self.reject); layout.addWidget(close)

    def _open_fuel_batch(self) -> None:
        tank = self._service.get_tank(self._tank_id)
        if tank: TankFuelBatchDialog(self._service, tank, self._refresh_batch_details, self).exec()

    def _refresh_batch_details(self, notify=True) -> None:
        tank = self._service.get_tank(self._tank_id)
        batch = self._service.get_fuel_batch(tank.current_fuel_batch_id) if tank and tank.current_fuel_batch_id else None
        self.current_fuel_value.set_fuel_type(batch.fuel_type if batch else "UNKNOWN"); self.current_batch_value.setText(batch.batch_name if batch else "No batch assigned"); self.density_value.setText(f"{batch.density_15_kg_m3:g} kg/m3" if batch else "--")
        if notify and self._on_changed is not None: self._on_changed()


class ConsumptionTanksDialog(QDialog):
    def __init__(self, service: FuelTankService, vessel_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service, self._vessel_id = service, vessel_id; self._forecast_by_tank = {}
        self.setWindowTitle("Tank Consumption Plan")
        screen = QGuiApplication.primaryScreen(); available = screen.availableGeometry() if screen else None
        width = min(1100, available.width() - 48) if available else 1100; height = min(750, available.height() - 48) if available else 750
        self.setMinimumSize(min(800, width), min(560, height)); self.resize(width, height)
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 20, 24, 18); layout.setSpacing(14)
        title_row = QHBoxLayout(); title = QLabel("TANK CONSUMPTION PLAN"); title.setObjectName("pageTitle"); title_row.addWidget(title); title_row.addStretch(); title_row.addWidget(QLabel("Fuel")); self.fuel_input = QComboBox(); self.fuel_input.addItems(FUEL_BATCH_TYPES); self.fuel_input.setMinimumWidth(140); title_row.addWidget(self.fuel_input); layout.addLayout(title_row)
        self.summary = QFrame(); self.summary.setObjectName("planSummaryCard"); summary_layout = QHBoxLayout(self.summary); summary_layout.setContentsMargins(16, 12, 16, 12); summary_layout.setSpacing(34)
        self.rob_summary = self._summary_value("CURRENT BUNKER-TANK ROB"); self.depletion_summary = self._summary_value("NEXT DEPLETION"); self.status_summary = self._summary_value("PLAN STATUS")
        summary_layout.addWidget(self.rob_summary); summary_layout.addWidget(self.depletion_summary, 1); summary_layout.addWidget(self.status_summary); layout.addWidget(self.summary)
        self.phase_scroll = QScrollArea(); self.phase_scroll.setWidgetResizable(True); self.phase_scroll.setFrameShape(QFrame.Shape.NoFrame); self.phase_content = QWidget(); self.phase_layout = QVBoxLayout(self.phase_content); self.phase_layout.setContentsMargins(0, 2, 6, 2); self.phase_layout.setSpacing(10); self.phase_layout.addStretch(); self.phase_scroll.setWidget(self.phase_content); layout.addWidget(self.phase_scroll, 1)
        self.add_phase_button = QPushButton("+ Add Phase"); self.add_phase_button.setObjectName("secondaryButton"); self.add_phase_button.clicked.connect(self._add_phase); layout.addWidget(self.add_phase_button, alignment=Qt.AlignmentFlag.AlignLeft)
        footer = QHBoxLayout(); self.effective_label = _muted(""); footer.addWidget(self.effective_label); footer.addStretch(); cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject); self.save_button = QPushButton("Save Active Plan"); self.save_button.setObjectName("primaryButton"); self.save_button.clicked.connect(self._apply); footer.addWidget(cancel); footer.addWidget(self.save_button); layout.addLayout(footer)
        self._phases: list[list[tuple[int, float]]] = []; self._effective = datetime.now(timezone.utc)
        self.fuel_input.currentTextChanged.connect(self._load_plan)
        self._load_plan()

    def _eligible_tanks(self):
        fuel = self.fuel_input.currentText(); existing = self._service.get_active_consumption_plan(self._vessel_id, fuel)
        batches = {item.id: item for item in self._service.list_fuel_batches(self._vessel_id)}
        return [(tank.id, tank.name) for tank in self._service.list_tanks(self._vessel_id) if tank.tank_type == "BUNKER" and tank.current_fuel_batch_id in batches and batches[tank.current_fuel_batch_id].fuel_type == fuel]

    def _load_plan(self) -> None:
        existing = self._service.get_active_consumption_plan(self._vessel_id, self.fuel_input.currentText())
        self._phases = [[(item.tank_id, item.allocation_fraction) for item in phase.tanks] for phase in existing.phases] if existing else []
        self._effective = existing.effective_from_utc if existing else datetime.now(timezone.utc)
        self._forecast_by_tank = self._load_forecasts()
        self._refresh_phases()

    def _summary_value(self, caption: str) -> QWidget:
        column = QWidget(); layout = QVBoxLayout(column); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(3); label = QLabel(caption); label.setObjectName("planSummaryLabel"); value = QLabel("—"); value.setObjectName("planSummaryValue"); value.setWordWrap(True); layout.addWidget(label); layout.addWidget(value); column.value = value; return column

    def _load_forecasts(self):
        # This is a read-only presentation adapter around the existing authority.
        parent = self.parent()
        forecast_service = getattr(parent, "_tank_forecast_service", None)
        if forecast_service is None: return {}
        try: return {item.tank_id: item for item in forecast_service.predict_plan_completion(self._vessel_id)}
        except Exception: return {}

    def _refresh_phases(self) -> None:
        while self.phase_layout.count():
            item = self.phase_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        names = dict(self._eligible_tanks())
        for index, phase in enumerate(self._phases): self.phase_layout.addWidget(self._phase_card(index, phase, names))
        self.phase_layout.addStretch()
        self.effective_label.setText(f"Plan effective: {_format_utc(self._effective.isoformat())}")
        self._refresh_summary(names)

    def _phase_card(self, index, phase, names):
        card = QFrame(); card.setObjectName("consumptionPhaseCard"); layout = QVBoxLayout(card); layout.setContentsMargins(16, 13, 16, 12); layout.setSpacing(7)
        heading = QHBoxLayout(); title = QLabel(f"PHASE {index + 1}"); title.setObjectName("phaseTitle"); heading.addWidget(title); heading.addStretch(); badge = QLabel(self._phase_status(index)); badge.setObjectName(f"phaseBadge{self._phase_status(index).title()}"); heading.addWidget(badge); layout.addLayout(heading)
        for tank_id, share in phase:
            row = QHBoxLayout(); name = QLabel(names.get(tank_id, str(tank_id))); name.setObjectName("phaseTankName"); row.addWidget(name); row.addStretch(); allocation = QLabel(f"{share * 100:.2f}%"); allocation.setObjectName("phaseAllocation"); row.addWidget(allocation); layout.addLayout(row)
        forecast = self._phase_forecast(index, phase); details = QGridLayout(); details.setHorizontalSpacing(24); details.setVerticalSpacing(4)
        details.addWidget(_muted("Estimated Start"), 0, 0); details.addWidget(QLabel(_forecast_time(forecast["start"])), 0, 1); details.addWidget(_muted("Estimated End"), 1, 0); details.addWidget(QLabel(_forecast_time(forecast["end"])), 1, 1)
        details.addWidget(_muted("Trigger Tank"), 0, 2); details.addWidget(QLabel(names.get(forecast["trigger"], "—") if forecast["trigger"] else "—"), 0, 3)
        if forecast["reason"]: details.addWidget(_muted(forecast["reason"]), 1, 2, 1, 2)
        layout.addLayout(details)
        for tank_id, _share in phase:
            item = self._forecast_by_tank.get(tank_id); depleted = item.estimated_depleted_at_utc if item else None
            line = QLabel(f"{names.get(tank_id, tank_id)} estimated depleted  {_forecast_time(depleted)}" + (f"  ·  {_time_remaining(depleted)} remaining" if depleted else "")); line.setObjectName("phaseForecastLine"); layout.addWidget(line)
        actions = QHBoxLayout(); edit = QPushButton("Edit"); edit.clicked.connect(lambda _, row=index: self._edit_phase_at(row)); up = QPushButton("Move Up"); up.setToolTip("Move phase up"); up.setEnabled(index > 0); up.clicked.connect(lambda: self._move_phase(index, -1)); down = QPushButton("Move Down"); down.setToolTip("Move phase down"); down.setEnabled(index < len(self._phases) - 1); down.clicked.connect(lambda: self._move_phase(index, 1)); delete = QPushButton("Delete"); delete.clicked.connect(lambda: self._delete_phase(index))
        for button in (edit, up, down, delete): actions.addWidget(button)
        actions.addStretch(); layout.addLayout(actions); return card

    def _phase_status(self, index):
        if not self._phases: return "PLANNED"
        plan = self._service.get_active_consumption_plan(self._vessel_id, self.fuel_input.currentText())
        if plan is None: return "PLANNED"
        active_sequence = self._active_phase_sequence(plan)
        if active_sequence is None: return "FORECAST UNAVAILABLE"
        sequence = index + 1
        if sequence < active_sequence: return "COMPLETED"
        if sequence == active_sequence: return "ACTIVE"
        if sequence == active_sequence + 1: return "NEXT"
        return "PLANNED"

    def _active_phase_sequence(self, plan):
        plan_tank_ids = {item.tank_id for phase in plan.phases for item in phase.tanks}
        forecasts = [self._forecast_by_tank[tank_id] for tank_id in plan_tank_ids if tank_id in self._forecast_by_tank]
        active = {item.active_phase_sequence for item in forecasts if item.active_phase_sequence is not None}
        if active:
            return min(active)
        if plan.phases:
            final_tanks = {item.tank_id for item in plan.phases[-1].tanks}
            if any(
                tank_id in self._forecast_by_tank
                and self._forecast_by_tank[tank_id].estimated_depleted_at_utc is not None
                for tank_id in final_tanks
            ):
                return plan.phases[-1].sequence_number + 1
        return None

    def _phase_forecast(self, index, phase):
        members = [(tank_id, self._forecast_by_tank.get(tank_id)) for tank_id, _share in phase]; depleted = [(tank_id, item.estimated_depleted_at_utc) for tank_id, item in members if item and item.estimated_depleted_at_utc]
        start = self._effective if index == 0 else next((item.planned_phase_start_utc for _tank, item in members if item and item.planned_phase_start_utc), None)
        trigger, end = min(depleted, key=lambda item: item[1]) if depleted else (None, None)
        reason = "Forecast unavailable" if not self._forecast_by_tank else ""
        return {"start": start, "end": end, "trigger": trigger, "reason": reason}

    def _refresh_summary(self, names):
        fuel = self.fuel_input.currentText()
        eligible_ids = set(names)
        masses = []
        unknown = 0
        for tank_id in eligible_ids:
            sounding = self._service.get_latest_sounding(tank_id)
            if sounding is None or sounding.calculated_mass_mt is None:
                unknown += 1
            else:
                masses.append(sounding.calculated_mass_mt)
        if unknown:
            reason = f"{unknown} bunker tank ROB{'s' if unknown != 1 else ''} unavailable"
            self.rob_summary.value.setText(f"—\n{reason}")
            self.rob_summary.value.setToolTip(reason)
        else:
            self.rob_summary.value.setText(f"{sum(masses):,.2f} MT" if eligible_ids else "—")
            self.rob_summary.value.setToolTip("")
        plan = self._service.get_active_consumption_plan(self._vessel_id, fuel)
        active_sequence = self._active_phase_sequence(plan) if plan else None
        active_tank_ids = {
            item.tank_id
            for phase in plan.phases if phase.sequence_number == active_sequence
            for item in phase.tanks
        } if plan and active_sequence is not None else set()
        forecast_items = [
            (tank_id, item.estimated_depleted_at_utc)
            for tank_id, item in self._forecast_by_tank.items()
            if tank_id in eligible_ids
            and tank_id in active_tank_ids
            and item.fuel_type == fuel
            and item.estimated_depleted_at_utc
        ]
        if forecast_items:
            tank_id, when = min(forecast_items, key=lambda item: item[1]); self.depletion_summary.value.setText(f"{names.get(tank_id, tank_id)}\n{_forecast_time(when)}\n{_time_remaining(when)} remaining")
        else: self.depletion_summary.value.setText("—")
        self.status_summary.value.setText("ACTIVE" if self._phases else "—")

    def _add_phase(self) -> None:
        self._edit_phase_at(len(self._phases))

    def _edit_phase_at(self, index: int) -> None:
        dialog = _PhaseEditorDialog(self._eligible_tanks(), self._phases[index] if index < len(self._phases) else [], self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if index == len(self._phases): self._phases.append(dialog.value())
            else: self._phases[index] = dialog.value()
            self._refresh_phases()

    def _delete_phase(self, row=None) -> None:
        row = len(self._phases) - 1 if row is None else row
        if 0 <= row < len(self._phases): self._phases.pop(row); self._refresh_phases()

    def _move_phase(self, row: int, direction: int) -> None:
        destination = row + direction
        if 0 <= row < len(self._phases) and 0 <= destination < len(self._phases): self._phases[row], self._phases[destination] = self._phases[destination], self._phases[row]; self._refresh_phases()

    def _apply(self) -> None:
        try:
            if not self._phases: raise FuelTankValidationError("Add at least one consumption phase.")
            phases = tuple(TankConsumptionPlanPhase(None, index + 1, tuple(TankConsumptionPlanPhaseTank(tank_id, share) for tank_id, share in phase)) for index, phase in enumerate(self._phases))
            self._service.save_consumption_plan(TankConsumptionPlan(None, self._vessel_id, self.fuel_input.currentText(), "ACTIVE", self._effective, phases))
        except (ValueError, FuelTankValidationError) as error:
            QMessageBox.warning(self, "Consumption plan not saved", str(error)); return
        self.accept()


class _PhaseEditorDialog(QDialog):
    def __init__(self, tanks, selected, parent=None):
        super().__init__(parent); self.setWindowTitle("Edit Consumption Phase")
        screen = QGuiApplication.primaryScreen(); available = screen.availableGeometry() if screen else None; width = min(850, available.width() - 48) if available else 850; height = min(600, available.height() - 48) if available else 600
        self.setMinimumSize(min(680, width), min(470, height)); self.resize(width, height); layout = QVBoxLayout(self); layout.setContentsMargins(22, 18, 22, 16); layout.setSpacing(12)
        heading = QLabel("EDIT CONSUMPTION PHASE"); heading.setObjectName("pageTitle"); layout.addWidget(heading); layout.addWidget(_muted("The phase ends when the first selected tank reaches 0 MT. The next planned phase then becomes active."))
        self.table = QTableWidget(0, 4); self.table.setHorizontalHeaderLabels(("Use", "Tank", "ROB / Forecast ROB", "Allocation %")); self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table.verticalHeader().setVisible(False); self.table.verticalHeader().setDefaultSectionSize(46); self.table.horizontalHeader().setStretchLastSection(False); layout.addWidget(self.table, 1)
        selected_by_id = dict(selected)
        for row, (tank_id, name) in enumerate(tanks):
            self.table.insertRow(row); use = QCheckBox(); use.setChecked(tank_id in selected_by_id); share = QDoubleSpinBox(); share.setRange(0.001, 100); share.setDecimals(2); share.setSuffix(" %"); share.setMinimumWidth(125); share.setValue(selected_by_id.get(tank_id, 0) * 100); share.setEnabled(use.isChecked())
            service = getattr(parent, "_service", None); latest = service.get_latest_sounding(tank_id) if service else None; forecast = getattr(parent, "_forecast_by_tank", {}).get(tank_id)
            rob = forecast.predicted_mass_mt if forecast and forecast.predicted_mass_mt is not None else (latest.calculated_mass_mt if latest else None)
            self.table.setCellWidget(row, 0, use); item = QTableWidgetItem(name); item.setData(Qt.ItemDataRole.UserRole, tank_id); self.table.setItem(row, 1, item); self.table.setItem(row, 2, QTableWidgetItem(f"{rob:,.2f} MT" if rob is not None else "—")); self.table.setCellWidget(row, 3, share)
            use.toggled.connect(lambda checked, current=row: self._toggle_row(current, checked)); use.toggled.connect(self._equal_split); share.valueChanged.connect(self._refresh_total)
        for column, width_value in enumerate((70, 350, 190, 150)): self.table.setColumnWidth(column, width_value)
        panel = QFrame(); panel.setObjectName("phaseValidationCard"); panel_layout = QHBoxLayout(panel); panel_layout.setContentsMargins(14, 10, 14, 10); self.count = QLabel(); self.total = QLabel(); self.validity = QLabel(); panel_layout.addWidget(self.count); panel_layout.addWidget(self.total); panel_layout.addStretch(); panel_layout.addWidget(self.validity); layout.addWidget(panel)
        footer = QHBoxLayout(); footer.addWidget(_muted("END CONDITION\nFirst selected tank depleted")); footer.addStretch(); cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject); self.save_button = QPushButton("Save Phase"); self.save_button.setObjectName("primaryButton"); self.save_button.clicked.connect(self._save); footer.addWidget(cancel); footer.addWidget(self.save_button); layout.addLayout(footer); self._refresh_total()
    def value(self): return [(self.table.item(row, 1).data(Qt.ItemDataRole.UserRole), self.table.cellWidget(row, 3).value() / 100) for row in range(self.table.rowCount()) if self.table.cellWidget(row, 0).isChecked()]
    def _toggle_row(self, row, checked): self.table.cellWidget(row, 3).setEnabled(checked); self._refresh_total()
    def _equal_split(self, *_):
        selected_rows = [row for row in range(self.table.rowCount()) if self.table.cellWidget(row, 0).isChecked()]
        if selected_rows:
            share = 100 / len(selected_rows)
            for row in selected_rows: self.table.cellWidget(row, 3).setValue(share)
        self._refresh_total()
    def _refresh_total(self, *_):
        values = self.value(); total = sum(share for _, share in values) * 100; valid = bool(values) and abs(total - 100) <= 1e-9
        self.count.setText(f"SELECTED TANKS\n{len(values)}"); self.total.setText(f"ALLOCATION TOTAL\n{total:.2f}%"); self.validity.setText("VALID" if valid else "MUST TOTAL 100%"); self.validity.setStyleSheet("color: #63C98D; font-weight: 700;" if valid else "color: #F29128; font-weight: 700;"); self.save_button.setEnabled(valid)
    def _save(self):
        values = self.value()
        if not values or abs(sum(share for _, share in values) - 1.0) > 1e-9: return
        self.accept()


class InternalTransferDialog(QDialog):
    """Small vessel-wide editor; transfers are tank-ledger events, not ROB changes."""
    def __init__(self, service: FuelTankService, vessel_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service, self._vessel_id = service, vessel_id
        self.setWindowTitle("Internal Transfer"); self.setMinimumWidth(560)
        layout = QVBoxLayout(self); layout.addWidget(_muted("Move an assigned fuel quantity between two compatible tanks."))
        form = QFormLayout()
        self.from_input = QComboBox(); self.to_input = QComboBox()
        for tank in service.list_tanks(vessel_id):
            label = f"{tank.name} ({self._fuel_for(tank)})"
            self.from_input.addItem(label, tank.id); self.to_input.addItem(label, tank.id)
        self.quantity_input = QLineEdit(); self.quantity_input.setPlaceholderText("MT")
        self.status_input = QComboBox(); self.status_input.addItems(("PLANNED", "COMPLETED"))
        self.time_input = QLineEdit(datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.remarks_input = QLineEdit(); self.fuel_value = QLabel("--")
        form.addRow("FROM Tank", self.from_input); form.addRow("TO Tank", self.to_input); form.addRow("Fuel", self.fuel_value)
        form.addRow("Quantity MT", self.quantity_input); form.addRow("Status", self.status_input); form.addRow("Effective Time UTC", self.time_input); form.addRow("Remarks", self.remarks_input)
        layout.addLayout(form)
        self.history_table = QTableWidget(0, 7); self.history_table.setHorizontalHeaderLabels(("Time UTC", "Status", "From", "To", "Fuel", "Quantity MT", "Remarks")); self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.history_table.horizontalHeader().setStretchLastSection(True); self.history_table.setMaximumHeight(180); layout.addWidget(self.history_table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.from_input.currentIndexChanged.connect(self._refresh_fuel); self._refresh_fuel(); self._refresh_history()

    def _fuel_for(self, tank: FuelTank) -> str:
        batch = self._service.get_fuel_batch(tank.current_fuel_batch_id) if tank.current_fuel_batch_id else None
        return batch.fuel_type if batch else "UNKNOWN"

    def _refresh_fuel(self) -> None:
        tank_id = self.from_input.currentData(); tank = self._service.get_tank(tank_id) if tank_id else None
        self.fuel_value.setText(self._fuel_for(tank) if tank else "UNKNOWN")

    def _refresh_history(self) -> None:
        tanks = {tank.id: tank.name for tank in self._service.list_tanks(self._vessel_id, include_inactive=True)}
        history = self._service.list_internal_fuel_transfers(self._vessel_id); self.history_table.setRowCount(0)
        for row, item in enumerate(history[:20]):
            self.history_table.insertRow(row)
            values = (_format_utc(item.effective_at_utc()), item.status, tanks.get(item.from_tank_id, "--"), tanks.get(item.to_tank_id, "--"), item.fuel_type, f"{item.quantity_mt:.2f}", item.remarks or "")
            for column, value in enumerate(values): self.history_table.setItem(row, column, QTableWidgetItem(value))

    def _save(self) -> None:
        try:
            timestamp = datetime.fromisoformat(self.time_input.text().strip())
            if timestamp.tzinfo is None: raise ValueError("Effective Time UTC must include +00:00.")
            status = self.status_input.currentText()
            transfer = InternalFuelTransfer(None, self._vessel_id, self.from_input.currentData(), self.to_input.currentData(), self.fuel_value.text(), float(self.quantity_input.text()), status, timestamp.isoformat(), timestamp.isoformat() if status == "COMPLETED" else None, self.remarks_input.text().strip() or None)
            self._service.create_internal_fuel_transfer(transfer)
        except (ValueError, FuelTankValidationError) as error:
            QMessageBox.warning(self, "Internal transfer not saved", str(error)); return
        self._refresh_history(); self.accept()


class TankSoundingSurveyDialog(QDialog):
    def __init__(self, service: FuelTankService, vessel_id: int, parent: QWidget | None = None, voyage_service=None) -> None:
        super().__init__(parent); self._service, self._vessel_id, self._voyage_service = service, vessel_id, voyage_service; self._rows = []; self._save_attempted = False
        self.setWindowTitle("Tank Sounding Survey"); self.setObjectName("soundingSurveyDialog")
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        maximum_width = min(1350, available.width() - 40) if available else 1350
        maximum_height = min(820, available.height() - 40) if available else 820
        self.setMinimumSize(min(1100, maximum_width), min(650, maximum_height))
        self.resize(maximum_width, maximum_height)
        layout = QVBoxLayout(self); layout.setContentsMargins(20, 18, 20, 18); layout.setSpacing(12)
        title_row = QHBoxLayout(); icon = QLabel("♒"); icon.setObjectName("surveyIcon"); title = QLabel("Tank Sounding Survey"); title.setObjectName("surveyTitle"); title_row.addWidget(icon); title_row.addWidget(title); title_row.addStretch(); layout.addLayout(title_row)
        common_box = QFrame(); common_box.setObjectName("surveyHeaderCard"); common = QGridLayout(common_box); common.setContentsMargins(14, 10, 14, 10); common.setHorizontalSpacing(10); common.setVerticalSpacing(8)
        self.time = QLineEdit(datetime.now(timezone.utc).isoformat(timespec="seconds")); self.trim = QLineEdit("0"); self.remarks = QLineEdit()
        self.time.setMinimumWidth(330); self.trim.setFixedWidth(120)
        common.addWidget(QLabel("Observation UTC"), 0, 0); common.addWidget(self.time, 0, 1); utc_note = QLabel("All times are in UTC"); utc_note.setObjectName("surveyHint"); common.addWidget(utc_note, 0, 2); common.addWidget(QLabel("Trim (m)"), 0, 3); common.addWidget(self.trim, 0, 4)
        common.addWidget(QLabel("Remarks"), 1, 0); common.addWidget(self.remarks, 1, 1, 1, 4); layout.addWidget(common_box)
        common.setColumnStretch(1, 5); common.setColumnStretch(2, 2); common.setColumnStretch(4, 2)
        self.table = QTableWidget(0, 10); self.table.setObjectName("soundingSurveyTable")
        self.table.setHorizontalHeaderLabels(("Include", "Tank", "Fuel / basis", "Measurement", "Reading cm", "Temp C", "VCF", "Volume m3", "MT", "Status"))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False); self.table.verticalHeader().setDefaultSectionSize(52); self.table.setAlternatingRowColors(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded); self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        header = self.table.horizontalHeader()
        widths = (70, 205, 180, 135, 118, 105, 120, 110, 92, 155)
        for column, width in enumerate(widths):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed); self.table.setColumnWidth(column, width)
        layout.addWidget(self.table, 1)
        batches = {batch.id: batch for batch in service.list_fuel_batches(vessel_id)}
        for tank in service.list_tanks(vessel_id): self._add_row(tank, batches.get(tank.current_fuel_batch_id))
        totals_box = QFrame(); totals_box.setObjectName("surveySummaryCard"); totals_layout = QHBoxLayout(totals_box); totals_layout.setContentsMargins(16, 12, 16, 12); totals_layout.setSpacing(20)
        total_column = QVBoxLayout(); totals_title = QLabel("SURVEY TOTAL ROB"); totals_title.setObjectName("surveySummaryTitle"); self.totals = QLabel("—"); self.totals.setObjectName("surveyTotalValue"); total_column.addWidget(totals_title); total_column.addWidget(self.totals); totals_layout.addLayout(total_column)
        status_column = QVBoxLayout(); status_label = QLabel("STATUS"); status_label.setObjectName("surveySummaryTitle"); self.completeness = QLabel("INCOMPLETE"); self.completeness.setObjectName("surveyStatusBadge"); self.completeness_reason = QLabel(""); self.completeness_reason.setObjectName("surveyHint"); status_column.addWidget(status_label); status_column.addWidget(self.completeness); status_column.addWidget(self.completeness_reason); totals_layout.addLayout(status_column, 1)
        self.summary_counts = {}
        for key, caption in (("included", "Included Tanks"), ("excluded", "Excluded Tanks"), ("known", "Tanks with ROB"), ("unknown", "Unknown ROB")):
            column = QVBoxLayout(); name = QLabel(caption); name.setObjectName("surveyHint"); value = QLabel("0"); value.setObjectName("surveyCountValue"); column.addWidget(name); column.addWidget(value); totals_layout.addLayout(column); self.summary_counts[key] = value
        layout.addWidget(totals_box)
        self.use_actual = QCheckBox("Use survey totals as Actual Vessel ROB"); self.use_actual.setToolTip("Checking this re-anchors aggregate vessel ROB. It is available only when every active tank has a known mass in this survey.")
        footer = QHBoxLayout(); actual_column = QVBoxLayout(); actual_column.addWidget(self.use_actual); actual_note = QLabel("When enabled, survey totals update the vessel's Actual ROB."); actual_note.setObjectName("surveyHint"); actual_column.addWidget(actual_note); footer.addLayout(actual_column); footer.addStretch()
        cancel = QPushButton("Cancel"); cancel.setObjectName("surveyCancelButton"); cancel.clicked.connect(self.reject); self.save_button = QPushButton("Save Survey"); self.save_button.setObjectName("primaryButton"); self.save_button.clicked.connect(self._save); footer.addWidget(cancel); footer.addWidget(self.save_button); layout.addLayout(footer)
        self.trim.textChanged.connect(self._refresh_all); self._refresh_all()

    def _add_row(self, tank: FuelTank, batch: FuelBatch | None) -> None:
        row_number = self.table.rowCount(); self.table.insertRow(row_number)
        include = QCheckBox(); include.setChecked(tank.tank_type == "BUNKER"); include.setToolTip("Include this tank in the survey")
        kind = QComboBox(); kind.addItems(MEASUREMENT_TYPES); kind.setCurrentText(tank.preferred_measurement_type); kind.setFixedWidth(135)
        reading, temp, vcf = QLineEdit(), QLineEdit(), QLineEdit()
        for widget, placeholder in ((reading, "cm"), (temp, "required for AUTO"), (vcf, "AUTO / manual override")):
            widget.setPlaceholderText(placeholder); widget.setFixedWidth(112)
        fuel = batch.fuel_type if batch else "UNASSIGNED"
        basis_widget = QWidget(); basis_layout = QVBoxLayout(basis_widget); basis_layout.setContentsMargins(6, 3, 6, 3); basis_layout.setSpacing(2)
        basis_layout.addWidget(FuelBadge(fuel), alignment=Qt.AlignmentFlag.AlignLeft)
        basis = QLabel(batch.batch_name if batch else "No batch assigned"); basis.setObjectName("surveyBasisText"); basis_layout.addWidget(basis)
        volume, mass, status = QLabel("—"), QLabel("—"), QLabel("PENDING")
        volume.setObjectName("surveyCalculated"); mass.setObjectName("surveyCalculated"); status.setObjectName("surveyStatus")
        row = (tank, include, kind, reading, temp, vcf, status, batch, volume, mass)
        self._rows.append(row)
        include_holder = QWidget(); include_layout = QHBoxLayout(include_holder); include_layout.setContentsMargins(0, 0, 0, 0); include_layout.addWidget(include, alignment=Qt.AlignmentFlag.AlignCenter)
        tank_label = QLabel(tank.name); tank_label.setObjectName("surveyTankName")
        self.table.setCellWidget(row_number, 0, include_holder); self.table.setCellWidget(row_number, 1, tank_label); self.table.setCellWidget(row_number, 2, basis_widget)
        for column, widget in ((3, kind), (4, reading), (5, temp), (6, vcf), (7, volume), (8, mass), (9, status)): self.table.setCellWidget(row_number, column, widget)
        include.toggled.connect(lambda *_unused, item=row: self._preview_row(item))
        for widget in (kind, reading, temp, vcf):
            signal = widget.currentTextChanged if isinstance(widget, QComboBox) else widget.textChanged
            signal.connect(lambda *_unused, item=row: self._preview_row(item))
        if self._rows[:-1]: self.setTabOrder(self._rows[-2][5], reading)
        self.setTabOrder(reading, temp); self.setTabOrder(temp, vcf)

    def _preview_row(self, row) -> None:
        tank, include, kind, reading, temp, vcf, status, batch, volume_label, mass_label = row
        for widget in (kind, reading, temp, vcf): widget.setEnabled(include.isChecked())
        if not include.isChecked(): self._set_row_status(status, "Excluded"); volume_label.setText("—"); mass_label.setText("—"); self._refresh_totals(); return
        entered = any(widget.currentText().strip() if isinstance(widget, QComboBox) else widget.text().strip() for widget in (reading, temp, vcf))
        if not reading.text().strip() or not self.trim.text().strip():
            self._set_row_status(status, "Reading required" if self._save_attempted else ("Incomplete" if entered else "--")); volume_label.setText("—"); mass_label.setText("—"); self._refresh_totals(); return
        try:
            reading_value = _optional_float(reading.text(), "Reading")
            trim_value = _optional_float(self.trim.text(), "Trim")
            if reading_value is None or trim_value is None: raise ValueError("Invalid reading")
            volume = self._service.calculate_calibrated_volume(tank.id, kind.currentText(), reading_value, trim_value)
            volume_label.setText(f"{volume:.3f}")
            manual_vcf = _optional_float(vcf.text(), "Manual VCF") if vcf.text().strip() else None
            result, effective_vcf, mode = self._service.calculate_tank_sounding_mass(volume, _optional_float(temp.text(), "Temperature") if temp.text().strip() else None, batch, manual_vcf)
            mass_label.setText(f"{result.mass_mt:.3f}"); mass_label.setToolTip(f"Volume @15: {result.standard_volume_15_m3:.3f} m3\nVCF: {effective_vcf:.5f} {mode}\nDensity @15: {batch.density_15_kg_m3:.3f} kg/m3"); vcf.setToolTip(f"{effective_vcf:.5f} {mode}"); self._set_row_status(status, "Ready")
        except ValueError as error:
            message = str(error).lower(); state = "No batch density" if "batch density" in message else ("Temperature required" if "temperature required" in message else ("Fuel basis unknown" if "fuel type" in message else ("Outside range" if "range" in message else ("No calibration" if "calibration" in message else "Invalid reading")))); self._set_row_status(status, state); volume_label.setText("—"); mass_label.setText("—")
        self._refresh_totals()

    def _refresh_all(self) -> None:
        for row in self._rows: self._preview_row(row)

    @staticmethod
    def _set_row_status(label: QLabel, state: str) -> None:
        colors = {"Ready": "#63C98D", "Excluded": "#8A9AA8", "Pending": "#E3A33B", "--": "#E3A33B", "No batch density": "#F29128", "Temperature required": "#59CBE8", "Fuel basis unknown": "#F29128", "No calibration": "#E3A33B", "Outside range": "#E37C4A"}
        label.setText(state); label.setStyleSheet(f"color:{colors.get(state, '#E3A33B')}; font-weight:700; font-size:10px;")

    def _refresh_totals(self) -> None:
        totals = {fuel: 0.0 for fuel in FUEL_BATCH_TYPES}; included = []; unknown = 0
        for tank, include, _kind, _reading, _temp, _vcf, _status, batch, _volume, mass in self._rows:
            if not include.isChecked(): continue
            included.append(tank)
            if batch is None or mass.text() in {"--", "—"}: unknown += 1
            else: totals[batch.fuel_type] += float(mass.text())
        visible = [f"{fuel}  {amount:,.2f} MT" for fuel, amount in totals.items() if amount]
        self.totals.setText("    ".join(visible) if visible else "—")
        active_count = len(self._service.list_tanks(self._vessel_id))
        complete = bool(included) and len(included) == active_count and unknown == 0
        self.completeness.setText("COMPLETE" if complete else "INCOMPLETE")
        self.completeness.setStyleSheet(f"color:{'#63C98D' if complete else '#F29128'}; font-weight:700; font-size:14px;")
        self.completeness_reason.setText("Complete" if complete else f"{unknown} included tank(s) have unknown MT")
        included_count = len(included); excluded_count = len(self._rows) - included_count; known_count = included_count - unknown
        self.summary_counts["included"].setText(str(included_count)); self.summary_counts["excluded"].setText(str(excluded_count)); self.summary_counts["known"].setText(str(known_count)); self.summary_counts["unknown"].setText(str(unknown))
        self.use_actual.setEnabled(complete)
        if not complete: self.use_actual.setChecked(False)

    def _save(self) -> None:
        try:
            self._save_attempted = True; self._refresh_all()
            effective = datetime.fromisoformat(self.time.text().strip())
            if effective.tzinfo is None: raise ValueError("Observation Time UTC must include +00:00.")
            rows = [{"include": include.isChecked(), "tank_id": tank.id, "reading_type": kind.currentText(), "reading_cm": reading.text(), "temperature_c": temp.text(), "manual_vcf": vcf.text()} for tank, include, kind, reading, temp, vcf, _status, _batch, _volume, _mass in self._rows]
            trim = _optional_float(self.trim.text(), "Trim")
            if trim is None: raise ValueError("Trim is required.")
            saved = self._service.save_sounding_survey(self._vessel_id, effective, trim, self.remarks.text().strip() or None, rows)
            if self.use_actual.isChecked():
                active = self._service.list_tanks(self._vessel_id)
                if len(saved) != len(active) or any(item.calculated_mass_mt is None for item in saved):
                    QMessageBox.warning(self, "Survey saved", "Survey soundings were saved, but Actual Vessel ROB was not updated because every active tank needs a known mass in this same survey.")
                elif self._voyage_service is None:
                    QMessageBox.warning(self, "Survey saved", "Survey soundings were saved, but Actual Vessel ROB is unavailable in this view.")
                else:
                    batches = {batch.id: batch for batch in self._service.list_fuel_batches(self._vessel_id)}; totals = {fuel: 0.0 for fuel in FUEL_BATCH_TYPES}
                    for item in saved:
                        batch = batches.get(item.fuel_batch_id)
                        if batch is None: raise ValueError("Survey fuel batch is unavailable.")
                        totals[batch.fuel_type] += item.calculated_mass_mt
                    self._voyage_service.save_actual_rob_observation(ActualROBObservation(None, self._vessel_id, effective, totals, self.remarks.text().strip() or None))
        except ValueError as error: QMessageBox.warning(self, "Survey not saved", str(error)); return
        self.accept()


class FuelTanksPage(QWidget):
    def __init__(self, vessel_service: VesselService, fuel_tank_service: FuelTankService, tank_forecast_service: TankForecastService | None = None, voyage_service=None) -> None:
        super().__init__()
        self._vessel_service, self._fuel_tank_service, self._tank_forecast_service, self._voyage_service = vessel_service, fuel_tank_service, tank_forecast_service, voyage_service
        self._selected_tank_id: int | None = None
        self._plan_forecasts = {}
        self.tank_cards: list[TankCard] = []
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(); content.setMinimumWidth(900)
        layout = QVBoxLayout(content); layout.setContentsMargins(32, 28, 32, 28); layout.setSpacing(14)
        layout.addWidget(PageHeader("Fuel Oil Tanks", "Vessel fuel tank overview and ROB management."))
        self.vessel_label = _muted("Vessel: Not configured"); layout.addWidget(self.vessel_label)
        self.empty_label = _muted(""); self.empty_label.setObjectName("notConfiguredStatus"); layout.addWidget(self.empty_label)
        self.arrangement_panel = QFrame(); self.arrangement_panel.setObjectName("tankWorkspace")
        self.arrangement_layout = QVBoxLayout(self.arrangement_panel); self.arrangement_layout.setContentsMargins(10, 8, 10, 10); self.arrangement_layout.setSpacing(14)
        self.add_tank_button = QPushButton("Add Tank"); self.add_tank_button.clicked.connect(self._add_tank)
        self.load_tank_set_button = QPushButton("Load Vessel Tank Set"); self.load_tank_set_button.clicked.connect(self._load_vessel_tank_set)
        self.survey_button = QPushButton("Update Tank ROBs"); self.survey_button.setObjectName("primaryButton"); self.survey_button.clicked.connect(self._open_survey)
        self.consumption_tanks_button = QPushButton("Tank Consumption Plan"); self.consumption_tanks_button.clicked.connect(self._configure_consumption_tanks)
        self.internal_transfer_button = QPushButton("Internal Transfer"); self.internal_transfer_button.clicked.connect(self._open_internal_transfer)
        self.primary_actions_layout = QGridLayout(); self.primary_actions_layout.setHorizontalSpacing(10); self.primary_actions_layout.setVerticalSpacing(8)
        for column, button in enumerate((self.survey_button, self.consumption_tanks_button, self.internal_transfer_button, self.add_tank_button, self.load_tank_set_button)):
            self.primary_actions_layout.addWidget(button, 0, column)
        layout.addLayout(self.primary_actions_layout)
        layout.addWidget(self.arrangement_panel)
        recent_title = QLabel("RECENT SOUNDINGS / ROB HISTORY"); recent_title.setObjectName("sectionTitle"); layout.addWidget(recent_title)
        self.history_table = QTableWidget(0, 12); self.history_table.setHorizontalHeaderLabels(("UTC", "Tank", "Type", "Reading (cm)", "Trim (m)", "Temp (°C)", "Observed (m³)", "VCF", "Volume @15°C (m³)", "MT", "Fuel", "Batch"))
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.history_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection); self.history_table.setAlternatingRowColors(True)
        self.history_table.verticalHeader().setVisible(False); self.history_table.horizontalHeader().setStretchLastSection(True); self.history_table.setMinimumHeight(190); layout.addWidget(self.history_table)
        self.history_empty_label = _muted("No tank soundings recorded."); layout.addWidget(self.history_empty_label); layout.addStretch()
        scroll.setWidget(content); root.addWidget(scroll)

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        self._selected_tank_id = None; self.tank_cards = []; self._clear_layout(self.arrangement_layout); self.history_table.setRowCount(0)
        if vessel is None:
            self.vessel_label.setText("Vessel: Not configured"); self.empty_label.setText("Configure a vessel before adding fuel oil tanks.")
            self.empty_label.show(); self.arrangement_panel.hide(); self.add_tank_button.setEnabled(False); self.load_tank_set_button.setEnabled(False); self.consumption_tanks_button.setEnabled(False); self.internal_transfer_button.setEnabled(False); self.survey_button.setEnabled(False); self.history_empty_label.show(); return
        self.vessel_label.setText(f"Vessel: {vessel.name}"); self.add_tank_button.setEnabled(True); self.load_tank_set_button.setEnabled(True); self.consumption_tanks_button.setEnabled(True); self.internal_transfer_button.setEnabled(True); self.survey_button.setEnabled(True)
        tanks = self._fuel_tank_service.list_tanks(vessel.id)
        try:
            self._plan_forecasts = {item.tank_id: item for item in self._tank_forecast_service.predict_plan_completion(vessel.id)} if self._tank_forecast_service else {}
        except Exception:
            self._plan_forecasts = {}
        if not tanks:
            self.empty_label.setText("No fuel oil tanks configured."); self.empty_label.show(); self.arrangement_panel.hide(); self.history_empty_label.show(); return
        self.empty_label.hide(); self.arrangement_panel.show()
        batches = {batch.id: batch for batch in self._fuel_tank_service.list_fuel_batches(vessel.id)}
        slots: dict[str, FuelTank] = {}
        other: list[FuelTank] = []
        for tank in tanks:
            position = _position_for_tank(tank.name)
            if position is None or position in slots:
                other.append(tank)
            else:
                slots[position] = tank
        history: list[tuple[FuelTank, TankSounding, str | None]] = []
        self._build_approved_groups(slots, other, batches, history)
        self._populate_history(history)

    def _build_approved_groups(self, slots, other, batches, history) -> None:
        groups = (("MDO Tanks", ("MDO_1_STOR", "MDO_2_STOR", "MDO_1_SERV", "MDO_2_SERV"), "MDO"), ("ULSFO Tanks", ("ULSFO_SETT", "ULSFO_SERV", "DEEP_3S"), "ULSFO"), ("VLSFO Tanks", ("DEEP_1P", "DEEP_1S", "DEEP_2P", "DEEP_2S", "DEEP_3P", "HFO_SETT", "HFO_SERV", "OVFLW_ER", "OVFLW_CH"), "VLSFO"))
        for title, positions, fuel in groups:
            tanks = [slots[position] for position in positions if position in slots]
            if not tanks: continue
            section = QWidget(); layout = QVBoxLayout(section); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(8)
            total, unknown = self._group_total(tanks)
            heading = QLabel(f"{title}     Total ROB: {total if total is not None else '—'}" + (f"  ·  {unknown} tank unknown" if unknown else "")); heading.setObjectName("tankGroupHeading"); heading.setStyleSheet(f"color:{fuel_color(fuel)};"); layout.addWidget(heading)
            grid = QGridLayout(); grid.setHorizontalSpacing(10); grid.setVerticalSpacing(10)
            split = 5 if title == "VLSFO Tanks" else len(tanks)
            for index, tank in enumerate(tanks): self._add_tank_card(grid, tank, index // split, index % split, batches, history, fuel.lower())
            for column in range(split): grid.setColumnStretch(column, 1)
            layout.addLayout(grid); self.arrangement_layout.addWidget(section)
        for tank in other:
            # Unmapped tanks remain visible without changing established identities.
            if tank is other[0]:
                heading = _section("OTHER TANKS"); self.arrangement_layout.addWidget(heading)
            self._add_tank_card(self.arrangement_layout, tank, batches, history, "other")

    def _group_total(self, tanks) -> tuple[str | None, int]:
        values = [self._fuel_tank_service.get_latest_sounding(tank.id) for tank in tanks]
        unknown = sum(1 for item in values if item is None or item.calculated_mass_mt is None)
        return (None if unknown else f"{sum(item.calculated_mass_mt for item in values):,.2f} MT", unknown)

    def _build_tank_plan(self, slots: dict[str, FuelTank], batches, history) -> QWidget:
        plan = QWidget()
        plan_layout = QHBoxLayout(plan); plan_layout.setContentsMargins(0, 0, 0, 0); plan_layout.setSpacing(12)
        plan_layout.addWidget(self._build_stacked_column("MDO", MDO_SLOTS, slots, batches, history, "mdo"))
        plan_layout.addWidget(self._build_stacked_column("SETTLING / SERVICE", SUPPORT_SLOTS, slots, batches, history, "support"))
        deep = QWidget()
        deep_layout = QVBoxLayout(deep); deep_layout.setContentsMargins(0, 0, 0, 0); deep_layout.setSpacing(5)
        heading = _section("DEEP TANKS"); heading.setStyleSheet("font-size: 8pt;"); deep_layout.addWidget(heading)
        deep_grid = QGridLayout(); deep_grid.setContentsMargins(0, 0, 0, 0); deep_grid.setSpacing(8)
        for index, position in enumerate(DEEP_SLOTS):
            tank = slots.get(position)
            if tank is not None:
                self._add_tank_card(deep_grid, tank, index // 3, index % 3, batches, history, "deep")
        deep_layout.addLayout(deep_grid)
        plan_layout.addWidget(deep)
        forward = QWidget()
        forward_layout = QVBoxLayout(forward); forward_layout.setContentsMargins(0, 0, 0, 0)
        forward_layout.addStretch()
        tank = slots.get("OVFLW_CH")
        if tank is not None:
            self._add_tank_card(forward_layout, tank, batches, history, "overflow")
        forward_layout.addStretch()
        plan_layout.addWidget(forward)
        return plan

    def _build_stacked_column(self, title: str, positions: tuple[str, ...], slots: dict[str, FuelTank], batches, history, kind: str) -> QWidget:
        column = QWidget()
        layout = QVBoxLayout(column); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(5)
        heading = _section(title); heading.setStyleSheet("font-size: 8pt;"); layout.addWidget(heading)
        for position in positions:
            tank = slots.get(position)
            if tank is not None:
                self._add_tank_card(layout, tank, batches, history, kind)
        layout.addStretch()
        return column

    def _add_tank_card(self, layout, tank: FuelTank, *args) -> None:
        if isinstance(layout, QGridLayout):
            row, column, batches, history, kind = args
        else:
            batches, history, kind = args
        latest = self._fuel_tank_service.get_latest_sounding(tank.id)
        batch = batches.get(tank.current_fuel_batch_id)
        card = TankCard(tank, batch.fuel_type if batch else None, batch.batch_name if batch else None, latest, kind, consumption_status=self._consumption_status(tank, batch, latest))
        card.selected.connect(self._select_tank); card.activated.connect(self._show_tank_details)
        if isinstance(layout, QGridLayout):
            layout.addWidget(card, row, column)
        else:
            layout.addWidget(card)
        self.tank_cards.append(card)
        for sounding in self._fuel_tank_service.list_sounding_history(tank.id):
            history.append((tank, sounding, batches.get(sounding.fuel_batch_id) or batch))

    def _consumption_status(self, tank: FuelTank, batch, latest: TankSounding | None) -> str:
        if batch is None or latest is None or latest.calculated_mass_mt is None:
            return "FORECAST UNAVAILABLE"
        plan = self._fuel_tank_service.get_active_consumption_plan(tank.vessel_id, batch.fuel_type)
        if plan is None:
            return "STANDBY"
        for phase in plan.phases:
            allocation = next((item.allocation_fraction for item in phase.tanks if item.tank_id == tank.id), None)
            if allocation is None:
                continue
            forecast = self._plan_forecasts.get(tank.id)
            if forecast is None or forecast.predicted_mass_mt is None:
                return "FORECAST UNAVAILABLE"
            active_sequence = forecast.active_phase_sequence
            if active_sequence is None:
                if forecast.estimated_depleted_at_utc is not None:
                    return f"DEPLETED\nDepleted UTC: {_format_utc(forecast.estimated_depleted_at_utc.isoformat())}"
                return "STANDBY"
            if phase.sequence_number < active_sequence:
                if forecast.estimated_depleted_at_utc is not None:
                    return f"DEPLETED\nDepleted UTC: {_format_utc(forecast.estimated_depleted_at_utc.isoformat())}"
                return "STANDBY"
            if phase.sequence_number == active_sequence:
                depleted = _format_utc(forecast.estimated_depleted_at_utc.isoformat()) if forecast and forecast.estimated_depleted_at_utc else "forecast unavailable"
                return f"ACTIVE CONSUMPTION · allocation {allocation * 100:g}%\nEstimated depleted UTC: {depleted} · Time remaining: {_time_remaining(forecast.estimated_depleted_at_utc) if forecast and forecast.estimated_depleted_at_utc else 'forecast unavailable'}"
            if phase.sequence_number == active_sequence + 1:
                start = forecast.planned_phase_start_utc
                start_text = _format_utc(start.isoformat()) if start else "forecast unavailable"
                starts_in = _time_remaining(start) if start else "forecast unavailable"
                return f"NEXT CONSUMPTION · allocation {allocation * 100:g}%\nPlanned start UTC: {start_text} · Starts in: {starts_in}"
            return f"PLANNED · phase {phase.sequence_number} · allocation {allocation * 100:g}%"
        return "STANDBY"

    def _populate_history(self, history: list[tuple[FuelTank, TankSounding, str | None]]) -> None:
        history.sort(key=lambda item: (item[1].effective_at_utc, item[1].id or 0), reverse=True)
        for row, (tank, sounding, batch) in enumerate(history[:20]):
            self.history_table.insertRow(row)
            values = (_format_utc(sounding.effective_at_utc), tank.name, sounding.reading_type, f"{sounding.reading_cm:.2f}", f"{sounding.trim_m:.2f}", "" if sounding.temperature_c is None else f"{sounding.temperature_c:.1f}", f"{sounding.calculated_volume_m3:.2f}", f"{sounding.manual_vcf:.5f}" if sounding.manual_vcf is not None else "--", f"{sounding.standard_volume_15_m3:.2f}" if sounding.standard_volume_15_m3 is not None else "--", f"{sounding.calculated_mass_mt:.2f}" if sounding.calculated_mass_mt is not None else "--", batch.fuel_type if batch else "", batch.batch_name if batch else "")
            for column, value in enumerate(values): self.history_table.setItem(row, column, QTableWidgetItem(value))
        self.history_empty_label.setVisible(not history)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None: item.widget().deleteLater()
            elif item.layout() is not None: self._clear_layout(item.layout())

    def _select_tank(self, tank_id: int) -> None:
        self._selected_tank_id = tank_id
        for card in self.tank_cards:
            card.set_selected(card._tank_id == tank_id)

    def _add_tank(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel and TankDialog(self._fuel_tank_service, vessel.id, parent=self).exec() == QDialog.DialogCode.Accepted: self.refresh()

    def _load_vessel_tank_set(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel:
            VesselTankSetDialog(self._fuel_tank_service, vessel.id, self).exec()
            self.refresh()

    def _configure_consumption_tanks(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel and ConsumptionTanksDialog(self._fuel_tank_service, vessel.id, self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _open_internal_transfer(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel and InternalTransferDialog(self._fuel_tank_service, vessel.id, self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _open_survey(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel and TankSoundingSurveyDialog(self._fuel_tank_service, vessel.id, self, self._voyage_service).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _edit_selected_tank(self) -> None:
        if self._selected_tank_id is None: return
        tank = self._fuel_tank_service.get_tank(self._selected_tank_id)
        if tank and TankDialog(self._fuel_tank_service, tank.vessel_id, tank, self).exec() == QDialog.DialogCode.Accepted: self.refresh()

    def _open_calibration(self) -> None:
        if self._selected_tank_id is None: return
        tank = self._fuel_tank_service.get_tank(self._selected_tank_id)
        if tank and CalibrationDialog(self._fuel_tank_service, tank, self).exec() == QDialog.DialogCode.Accepted: self.refresh()

    def _update_rob(self) -> None:
        if self._selected_tank_id is None: return
        tank = self._fuel_tank_service.get_tank(self._selected_tank_id)
        if tank and UpdateTankROBDialog(self._fuel_tank_service, tank, self).exec() == QDialog.DialogCode.Accepted: self.refresh()

    def _open_fuel_batch(self) -> None:
        if self._selected_tank_id is None: return
        tank = self._fuel_tank_service.get_tank(self._selected_tank_id)
        if tank: TankFuelBatchDialog(self._fuel_tank_service, tank, self.refresh, self).exec()

    def _show_tank_details(self, tank_id: int) -> None:
        tank = self._fuel_tank_service.get_tank(tank_id)
        if tank is None: return
        batch = self._fuel_tank_service.get_fuel_batch(tank.current_fuel_batch_id) if tank.current_fuel_batch_id else None
        predicted = None
        empty_text = "--"
        if self._tank_forecast_service is not None:
            try:
                forecast = next((item for item in self._tank_forecast_service.predict_tank_rob_at(tank.vessel_id, datetime.now(timezone.utc)) if item.tank_id == tank_id), None)
                predicted = forecast.predicted_mass_mt if forecast else None
                empty = next((item for item in self._tank_forecast_service.predict_tank_empty_times(tank.vessel_id, datetime.now(timezone.utc)) if item.tank_id == tank_id), None)
                if empty is not None:
                    empty_text = _format_utc(empty.estimated_empty_at_utc.isoformat()) if empty.estimated_empty_at_utc else (empty.issue or empty.state)
            except Exception:
                predicted = None
        TankDetailsDialog(self._fuel_tank_service, tank, batch.fuel_type if batch else None, batch.batch_name if batch else None, self._fuel_tank_service.get_latest_sounding(tank_id), self, self.refresh, predicted, empty_text).exec()


def _normalized_name(name: str) -> str:
    normalized = name.upper()
    for source, replacement in (
        ("STARBOARD", "S"), ("STBD", "S"), ("PORT", "P"), ("TANK", "TK"),
        ("SETTLING", "SETT"), ("SERVICE", "SERV"), ("STORAGE", "STOR"),
        ("LSHFO", "ULSFO"), ("LSFO", "ULSFO"), ("MDO", "DO"),
    ):
        normalized = normalized.replace(source, replacement)
    return re.sub(r"[^A-Z0-9]", "", normalized)


def _position_for_tank(name: str) -> str | None:
    normalized = _normalized_name(name)
    deep_match = re.search(r"(?:HFO|ULSFO)DEEP(?:TK)?([123])([PS])", normalized)
    if deep_match:
        return f"DEEP_{deep_match.group(1)}{deep_match.group(2)}"
    mdo_match = re.search(r"NO([12])DO(?:TK)?(SERV|STOR)", normalized)
    if mdo_match:
        return f"MDO_{mdo_match.group(1)}_{mdo_match.group(2)}"
    if "OVFLWTKER" in normalized:
        return "OVFLW_ER"
    if "OVFLWTKCH" in normalized:
        return "OVFLW_CH"
    for fuel, label in (("HFO", "HFO"), ("ULSFO", "ULSFO")):
        if f"{fuel}SETT" in normalized:
            return f"{label}_SETT"
        if f"{fuel}SERV" in normalized:
            return f"{label}_SERV"
    return None


def _section(text: str) -> QLabel:
    label = QLabel(text); label.setObjectName("sectionTitle"); return label


def _muted(text: str) -> QLabel:
    label = QLabel(text); label.setObjectName("mutedText"); label.setWordWrap(True); return label


def _format_utc(value: str) -> str:
    try: return datetime.fromisoformat(value).strftime("%d %b %Y %H:%M")
    except ValueError: return value


def _forecast_time(value: datetime | None) -> str:
    return _format_utc(value.isoformat()) if value else "—"


def _time_remaining(value: datetime) -> str:
    seconds = int((value - datetime.now(timezone.utc)).total_seconds())
    if seconds <= 0: return "now / passed"
    hours, remainder = divmod(seconds, 3600)
    return f"{hours // 24}d {hours % 24}h {remainder // 60}m"


def _card_value(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("tankRob")
    return label


def _card_meta(text: str) -> QLabel:
    label = QLabel(text); label.setObjectName("tankMeta"); return label


def _optional_float(value: str, label: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"{label} must be numeric.") from error


def _optional_number(value: float | None) -> str:
    return "" if value is None else f"{value:g}"


def _short_batch_name(name: str) -> str:
    return name if len(name) <= 9 else f"{name[:8]}…"


def _short_display_name(name: str) -> str:
    position = _position_for_tank(name)
    labels = {
        "MDO_1_SERV": "DO SVC 1", "MDO_2_SERV": "DO SVC 2", "MDO_1_STOR": "DO STO 1", "MDO_2_STOR": "DO STO 2",
        "HFO_SETT": "HFO SETT", "HFO_SERV": "HFO SERV", "ULSFO_SETT": "ULS SETT", "ULSFO_SERV": "ULS SERV",
        "OVFLW_ER": "ER OVFLW", "OVFLW_CH": "CH OVFLW",
    }
    if position in labels:
        return labels[position]
    if position and position.startswith("DEEP_"):
        return position.removeprefix("DEEP_")
    return name if len(name) <= 14 else f"{name[:13]}…"
