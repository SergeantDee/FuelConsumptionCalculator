from __future__ import annotations

import re
from datetime import datetime, timezone

from PySide6.QtCore import QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from fuel_consumption_calculator.domain.fuel_tank import (
    FUEL_BATCH_TYPES,
    FUEL_TANK_TYPES,
    FuelBatch,
    FuelTank,
    TankSounding,
)
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService, FuelTankValidationError
from fuel_consumption_calculator.services.tank_forecast_service import TankForecastService
from fuel_consumption_calculator.domain.voyage import ActualROBObservation
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader
from fuel_consumption_calculator.ui.pages.fuel_tank_operational_dialogs import CalibrationDialog, UpdateTankROBDialog


FUEL_COLORS = {"ULSFO": "#7ec8f5", "VLSFO": "#b293e8", "MDO": "#f1c778"}
NEUTRAL_LEVEL_COLOR = "#477a91"
MDO_SLOTS = ("MDO_1_SERV", "MDO_2_SERV", "MDO_1_STOR", "MDO_2_STOR")
SUPPORT_SLOTS = ("ULSFO_SETT", "ULSFO_SERV", "HFO_SERV", "HFO_SETT", "OVFLW_ER")
DEEP_SLOTS = ("DEEP_3P", "DEEP_2P", "DEEP_1P", "DEEP_3S", "DEEP_2S", "DEEP_1S")
VESSEL_TANK_SET = (
    ("HFO DEEP TK 3P", "BUNKER", True), ("HFO DEEP TK 2P", "BUNKER", True),
    ("HFO DEEP TK 1P", "BUNKER", True), ("LSFO DEEP TK 3S", "BUNKER", True),
    ("HFO DEEP TK 2S", "BUNKER", True), ("HFO DEEP TK 1S", "BUNKER", True),
    ("NO.1 DO STOR.TK", "BUNKER", True), ("NO.2 DO STOR.TK", "BUNKER", True),
    ("HFO SETT.TK", "SETTLING", False), ("LSHFO SETT.TK", "SETTLING", False),
    ("HFO SERV.TK", "SERVICE", False), ("LSHFO SERV.TK", "SERVICE", False),
    ("NO.1 DO SERV.TK", "SERVICE", False), ("NO.2 DO SERV.TK", "SERVICE", False),
    ("OVFLW TK CH", "OTHER", False), ("OVFLW TK ER", "OTHER", False),
)


class TankLevelWidget(QWidget):
    def __init__(self, fill_percent: float | None, fuel_type: str | None, width: int, height: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._unknown = fill_percent is None
        self._fill_percent = 0.0 if fill_percent is None else max(0.0, min(100.0, fill_percent))
        self._color = QColor(FUEL_COLORS.get(fuel_type, NEUTRAL_LEVEL_COLOR))
        self.setFixedSize(width, height)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outline = self.rect().adjusted(2, 2, -2, -2)
        painter.setPen(QColor("#5c8194"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(outline, 4, 4)
        if self._unknown:
            painter.setPen(QColor("#6f8796"))
            painter.drawText(outline, Qt.AlignmentFlag.AlignCenter, "?")
            return
        height = round(outline.height() * self._fill_percent / 100)
        if height:
            liquid = outline.adjusted(2, outline.height() - height + 2, -2, -2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color)
            painter.drawRect(liquid)


class TankCard(QFrame):
    selected = Signal(int)
    activated = Signal(int)

    SIZES = {
        "mdo": (120, 72, 9, 52),
        "support": (110, 58, 8, 40),
        "deep": (152, 152, 12, 128),
        "overflow": (128, 142, 10, 118),
        "other": (104, 80, 10, 58),
    }

    def __init__(self, tank: FuelTank, fuel_type: str | None, batch_name: str | None, latest: TankSounding | None, kind: str = "other", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tank_id = tank.id
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.kind = kind
        width, height, gauge_width, gauge_height = self.SIZES[kind]
        self.setFixedSize(width, height)
        self.setToolTip(tank.name)
        fill_percent = None if latest is None else latest.calculated_volume_m3 / tank.capacity_m3 * 100
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 6, 5, 6)
        layout.setSpacing(4)
        details = QVBoxLayout()
        details.setSpacing(0)
        name = QLabel(_short_display_name(tank.name))
        name.setStyleSheet("font-size: 10pt; font-weight: 700;" if kind in {"deep", "overflow"} else "font-size: 8pt; font-weight: 700;")
        details.addWidget(name)
        marker = QLabel(f"● {fuel_type}" if fuel_type else "FUEL --")
        marker.setObjectName("fuelIndicator")
        marker.setStyleSheet(f"color: {FUEL_COLORS.get(fuel_type, '#8caabd')}; font-weight: 700; font-size: 7pt;")
        details.addWidget(marker)
        if batch_name and (kind in {"deep", "overflow"} or len(batch_name) <= 8):
            batch = _muted(_short_batch_name(batch_name))
            batch.setStyleSheet("font-size: 7pt;")
            batch.setToolTip(batch_name)
            details.addWidget(batch)
        if latest is None:
            details.addWidget(_card_value("MT --"))
            details.addWidget(_card_value("ROB --"))
        else:
            if latest.calculated_mass_mt is not None:
                details.addWidget(_card_value(f"{latest.calculated_mass_mt:.3f} MT"))
            else:
                details.addWidget(_card_value("MT --"))
            details.addWidget(_card_value(f"{max(0.0, min(100.0, fill_percent or 0.0)):.0f}%"))
        details.addStretch()
        layout.addLayout(details, 1)
        layout.addWidget(TankLevelWidget(fill_percent, fuel_type, gauge_width, gauge_height), alignment=Qt.AlignmentFlag.AlignVCenter)

    def set_selected(self, selected: bool) -> None:
        self.setStyleSheet("QFrame#card { border: 2px solid #1aa0b8; }" if selected else "")

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
        layout.addWidget(_muted("Select the tanks to create and enter each actual capacity before confirming."))
        self.tank_table = QTableWidget(len(VESSEL_TANK_SET), 5)
        self.tank_table.setHorizontalHeaderLabels(("Include", "Tank Name", "Tank Type", "Capacity m³", "Bunker Receiving"))
        self.tank_table.verticalHeader().setVisible(False)
        self.tank_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tank_table.horizontalHeader().setStretchLastSection(True)
        self.row_controls: list[tuple[QCheckBox, QDoubleSpinBox, QCheckBox]] = []
        for row, (name, tank_type, receiving_default) in enumerate(VESSEL_TANK_SET):
            include = QCheckBox(); include.setChecked(True)
            capacity = QDoubleSpinBox(); capacity.setRange(0.0, 100000.0); capacity.setDecimals(2); capacity.setSuffix(" m³"); capacity.setSpecialValueText("Required")
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

    def create_selected_tanks(self) -> tuple[int, int]:
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
        existing_names = {_normalized_name(tank.name) for tank in existing_tanks}
        existing_positions = {_position_for_tank(tank.name) for tank in existing_tanks}
        created = existing = 0
        for name, tank_type, receiving, capacity in selected:
            position = _position_for_tank(name)
            if _normalized_name(name) in existing_names or (position is not None and position in existing_positions):
                existing += 1
                continue
            saved = self._service.create_tank(FuelTank(
                id=None, vessel_id=self._vessel_id, name=name, tank_type=tank_type, capacity_m3=capacity,
                preferred_measurement_type="SOUNDING", bunker_receiving_eligible=receiving,
            ))
            existing_names.add(_normalized_name(saved.name))
            existing_positions.add(_position_for_tank(saved.name))
            created += 1
        return created, existing

    def _create_selected(self) -> None:
        try:
            created, existing = self.create_selected_tanks()
        except ValueError as error:
            QMessageBox.warning(self, "Tank set not created", str(error))
            return
        self.summary_label.setText(f"{created} tank{'s' if created != 1 else ''} created, {existing} already existed.")


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
    def __init__(self, service: FuelTankService, tank: FuelTank, fuel_type: str | None, batch_name: str | None, latest: TankSounding | None, parent: QWidget | None = None, on_changed=None, predicted_mass_mt: float | None = None) -> None:
        super().__init__(parent)
        self._service, self._tank_id, self._on_changed = service, tank.id, on_changed
        self.setWindowTitle("Tank Details"); self.setMinimumWidth(380)
        layout = QVBoxLayout(self); layout.addWidget(QLabel(tank.name, objectName="pageTitle")); form = QFormLayout()
        self.current_fuel_value = QLabel(fuel_type or "UNKNOWN"); self.current_batch_value = QLabel(batch_name or "No batch assigned"); self.density_value = QLabel()
        self._refresh_batch_details(notify=False)
        values = (("Tank Type", tank.tank_type), ("Capacity", f"{tank.capacity_m3:.2f} m3"), ("Active", "Yes" if tank.is_active else "No"), ("Bunker Receiving", "Yes" if tank.bunker_receiving_eligible else "No"), ("Current Fuel", self.current_fuel_value), ("Current Batch", self.current_batch_value), ("Density @15 C", self.density_value), ("Latest Observed Volume", f"{latest.calculated_volume_m3:.2f} m3" if latest else "No sounding"), ("Latest Manual VCF", f"{latest.manual_vcf:.5f}" if latest and latest.manual_vcf is not None else "--"), ("Latest Volume @15 C", f"{latest.standard_volume_15_m3:.2f} m3" if latest and latest.standard_volume_15_m3 is not None else "--"), ("Actual ROB", f"{latest.calculated_mass_mt:.2f} MT" if latest and latest.calculated_mass_mt is not None else "--"), ("Estimated ROB", f"{predicted_mass_mt:.2f} MT" if predicted_mass_mt is not None else "--"), ("Fill", f"{max(0.0, min(100.0, latest.calculated_volume_m3 / tank.capacity_m3 * 100)):.1f}%" if latest else "--"), ("Latest Sounding", _format_utc(latest.effective_at_utc) if latest else "No sounding"))
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
        self.current_fuel_value.setText(batch.fuel_type if batch else "UNKNOWN"); self.current_batch_value.setText(batch.batch_name if batch else "No batch assigned"); self.density_value.setText(f"{batch.density_15_kg_m3:g} kg/m3" if batch else "--")
        if notify and self._on_changed is not None: self._on_changed()


class ConsumptionTanksDialog(QDialog):
    def __init__(self, service: FuelTankService, vessel_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service, self._vessel_id = service, vessel_id
        self.setWindowTitle("Consumption Tanks")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select active bunker/storage tanks. Equal depletion is split by fuel."))
        current = service.list_consumption_allocation_events(vessel_id)
        selected = set(current[-1].tank_ids) if current else set()
        self._checks: dict[int, QCheckBox] = {}
        for tank in service.list_tanks(vessel_id):
            if tank.tank_type != "BUNKER":
                continue
            check = QCheckBox(f"{tank.name}  —  Consuming")
            check.setChecked(tank.id in selected)
            self._checks[tank.id] = check
            layout.addWidget(check)
        form = QFormLayout()
        self.effective_input = QLineEdit(datetime.now(timezone.utc).isoformat(timespec="seconds"))
        form.addRow("Effective UTC", self.effective_input)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        apply = buttons.addButton("Apply Consumption Tanks", QDialogButtonBox.ButtonRole.AcceptRole)
        apply.clicked.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply(self) -> None:
        try:
            effective = datetime.fromisoformat(self.effective_input.text().strip())
            if effective.tzinfo is None:
                raise ValueError("Effective UTC must include +00:00.")
            self._service.apply_consumption_tanks(self._vessel_id, [tank_id for tank_id, check in self._checks.items() if check.isChecked()], effective)
        except (ValueError, FuelTankValidationError) as error:
            QMessageBox.warning(self, "Consumption tanks not applied", str(error))
            return
        self.accept()


class TankSoundingSurveyDialog(QDialog):
    def __init__(self, service: FuelTankService, vessel_id: int, parent: QWidget | None = None, voyage_service=None) -> None:
        super().__init__(parent); self._service, self._vessel_id, self._voyage_service = service, vessel_id, voyage_service; self._rows = []
        self.setWindowTitle("Update Tank ROBs"); self.resize(860, 620)
        layout = QVBoxLayout(self); common = QFormLayout()
        self.time = QLineEdit(datetime.now(timezone.utc).isoformat(timespec="seconds")); self.trim = QLineEdit("0"); self.remarks = QLineEdit()
        common.addRow("Observation Time UTC", self.time); common.addRow("Trim m", self.trim); common.addRow("Survey Remarks", self.remarks); layout.addLayout(common)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); content = QWidget(); rows = QVBoxLayout(content)
        batches = {batch.id: batch for batch in service.list_fuel_batches(vessel_id)}
        for tank in service.list_tanks(vessel_id):
            batch = batches.get(tank.current_fuel_batch_id); box = QFrame(); box.setObjectName("panel"); grid = QGridLayout(box)
            include = QCheckBox("Include"); include.setChecked(tank.tank_type == "BUNKER")
            reading, temp, vcf = QLineEdit(), QLineEdit(), QLineEdit(); kind = QComboBox(); kind.addItems(MEASUREMENT_TYPES); kind.setCurrentText(tank.preferred_measurement_type)
            preview = QLabel("Reading required"); preview.setWordWrap(True)
            grid.addWidget(include, 0, 0); grid.addWidget(QLabel(tank.name), 0, 1); grid.addWidget(QLabel(batch.fuel_type if batch else "UNKNOWN"), 0, 2); grid.addWidget(QLabel(batch.batch_name if batch else "No batch"), 0, 3)
            for column, (label, widget) in enumerate((("Type", kind), ("Reading cm", reading), ("Temperature C", temp), ("Manual VCF", vcf)), 1): grid.addWidget(QLabel(label), 1, column); grid.addWidget(widget, 2, column)
            grid.addWidget(preview, 3, 0, 1, 5); row = (tank, include, kind, reading, temp, vcf, preview, batch); self._rows.append(row)
            for widget in (kind, reading, temp, vcf):
                signal = widget.currentTextChanged if isinstance(widget, QComboBox) else widget.textChanged
                signal.connect(lambda *_unused, row=row: self._preview_row(row))
            rows.addWidget(box)
        rows.addStretch(); scroll.setWidget(content); layout.addWidget(scroll)
        self.use_actual = QCheckBox("Use complete survey totals as Actual Vessel ROB"); layout.addWidget(self.use_actual)
        self.totals = QLabel("Survey Totals: --"); layout.addWidget(self.totals)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def _preview_row(self, row) -> None:
        tank, include, kind, reading, _temp, vcf, preview, batch = row
        if not reading.text().strip() or not self.trim.text().strip(): preview.setText("Reading required"); return
        try:
            reading_value = _optional_float(reading.text(), "Reading")
            trim_value = _optional_float(self.trim.text(), "Trim")
            if reading_value is None or trim_value is None: preview.setText("Reading required"); return
            volume = self._service.calculate_calibrated_volume(tank.id, kind.currentText(), reading_value, trim_value)
            if not vcf.text().strip(): preview.setText(f"Observed Volume: {volume:.3f} m3 | MT -- (Manual VCF optional)")
            elif batch is None: preview.setText(f"Observed Volume: {volume:.3f} m3 | No fuel batch")
            else:
                vcf_value = _optional_float(vcf.text(), "Manual VCF")
                result = self._service.calculate_manual_vcf_mass(volume, vcf_value, batch.density_15_kg_m3); preview.setText(f"Observed Volume: {volume:.3f} m3 | Volume @15: {result.standard_volume_15_m3:.3f} m3 | MT: {result.mass_mt:.3f}")
        except ValueError as error: preview.setText(str(error))

    def _save(self) -> None:
        try:
            effective = datetime.fromisoformat(self.time.text().strip())
            if effective.tzinfo is None: raise ValueError("Observation Time UTC must include +00:00.")
            rows = [{"include": include.isChecked(), "tank_id": tank.id, "reading_type": kind.currentText(), "reading_cm": reading.text(), "temperature_c": temp.text(), "manual_vcf": vcf.text()} for tank, include, kind, reading, temp, vcf, _preview, _batch in self._rows]
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
        self.tank_cards: list[TankCard] = []
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(); content.setMinimumWidth(900)
        layout = QVBoxLayout(content); layout.setContentsMargins(32, 28, 32, 28); layout.setSpacing(14)
        layout.addWidget(PageHeader("Fuel Oil Tanks", "Vessel fuel tank overview and ROB management."))
        self.vessel_label = _muted("Vessel: Not configured"); layout.addWidget(self.vessel_label)
        self.empty_label = _muted(""); self.empty_label.setObjectName("notConfiguredStatus"); layout.addWidget(self.empty_label)
        self.arrangement_panel = QFrame(); self.arrangement_panel.setObjectName("panel")
        panel_layout = QVBoxLayout(self.arrangement_panel); panel_layout.setContentsMargins(18, 16, 18, 18); panel_layout.setSpacing(10)
        title = QLabel("TANK ARRANGEMENT"); title.setObjectName("sectionTitle"); panel_layout.addWidget(title)
        self.tank_strip = QScrollArea()
        self.tank_strip.setWidgetResizable(False)
        self.tank_strip.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tank_strip.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tank_strip.setFrameShape(QFrame.Shape.NoFrame)
        self.tank_strip.setStyleSheet("""
            QScrollBar:horizontal { height: 8px; background: #16252d; margin: 1px 8px; }
            QScrollBar::handle:horizontal { background: #426778; border-radius: 4px; min-width: 28px; }
            QScrollBar::handle:horizontal:hover { background: #5a8799; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
        """)
        self.tank_strip.setFixedHeight(282)
        self.strip_content = QWidget()
        self.strip_content.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.arrangement_layout = QVBoxLayout(self.strip_content)
        self.arrangement_layout.setContentsMargins(0, 0, 0, 0)
        self.arrangement_layout.setSpacing(12)
        self.tank_strip.setWidget(self.strip_content)
        panel_layout.addWidget(self.tank_strip)
        layout.addWidget(self.arrangement_panel)
        actions = QHBoxLayout()
        self.add_tank_button = QPushButton("Add Tank"); self.add_tank_button.setObjectName("primaryButton"); self.add_tank_button.clicked.connect(self._add_tank)
        self.load_tank_set_button = QPushButton("Load Vessel Tank Set"); self.load_tank_set_button.clicked.connect(self._load_vessel_tank_set)
        self.survey_button = QPushButton("Update Tank ROBs"); self.survey_button.setObjectName("primaryButton"); self.survey_button.clicked.connect(self._open_survey)
        self.consumption_tanks_button = QPushButton("Apply Consumption Tanks"); self.consumption_tanks_button.clicked.connect(self._configure_consumption_tanks)
        self.update_rob_button = QPushButton("Update ROB"); self.update_rob_button.setEnabled(False); self.update_rob_button.clicked.connect(self._update_rob)
        self.calibration_button = QPushButton("Calibration"); self.calibration_button.setEnabled(False); self.calibration_button.clicked.connect(self._open_calibration)
        self.fuel_batch_button = QPushButton("Fuel / Batch"); self.fuel_batch_button.setEnabled(False); self.fuel_batch_button.clicked.connect(self._open_fuel_batch)
        self.edit_tank_button = QPushButton("Edit Selected Tank"); self.edit_tank_button.setEnabled(False); self.edit_tank_button.clicked.connect(self._edit_selected_tank)
        actions.addWidget(self.survey_button); actions.addWidget(self.add_tank_button); actions.addWidget(self.load_tank_set_button); actions.addWidget(self.consumption_tanks_button); actions.addWidget(self.edit_tank_button); actions.addWidget(self.update_rob_button); actions.addWidget(self.calibration_button); actions.addWidget(self.fuel_batch_button); actions.addStretch(); layout.addLayout(actions)
        recent_title = QLabel("RECENT SOUNDINGS / ROB HISTORY"); recent_title.setObjectName("sectionTitle"); layout.addWidget(recent_title)
        self.history_table = QTableWidget(0, 11); self.history_table.setHorizontalHeaderLabels(("UTC", "Tank", "Type", "Reading", "Trim", "Temperature", "Observed Volume m3", "VCF", "Volume @15 m3", "MT", "Fuel"))
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.history_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection); self.history_table.setAlternatingRowColors(True)
        self.history_table.horizontalHeader().setStretchLastSection(True); self.history_table.setMinimumHeight(190); layout.addWidget(self.history_table)
        self.history_empty_label = _muted("No tank soundings recorded."); layout.addWidget(self.history_empty_label); layout.addStretch()
        scroll.setWidget(content); root.addWidget(scroll)

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        self._selected_tank_id = None; self.tank_cards = []; self.edit_tank_button.setEnabled(False); self.update_rob_button.setEnabled(False); self.calibration_button.setEnabled(False); self.fuel_batch_button.setEnabled(False); self._clear_layout(self.arrangement_layout); self.history_table.setRowCount(0)
        if vessel is None:
            self.vessel_label.setText("Vessel: Not configured"); self.empty_label.setText("Configure a vessel before adding fuel oil tanks.")
            self.empty_label.show(); self.arrangement_panel.hide(); self.add_tank_button.setEnabled(False); self.load_tank_set_button.setEnabled(False); self.consumption_tanks_button.setEnabled(False); self.survey_button.setEnabled(False); self.history_empty_label.show(); return
        self.vessel_label.setText(f"Vessel: {vessel.name}"); self.add_tank_button.setEnabled(True); self.load_tank_set_button.setEnabled(True); self.consumption_tanks_button.setEnabled(True); self.survey_button.setEnabled(True)
        tanks = self._fuel_tank_service.list_tanks(vessel.id)
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
        orientation = _muted("AFT  ←----------------------------------------------------------→  FORWARD")
        orientation.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.arrangement_layout.addWidget(orientation)
        self.arrangement_layout.addWidget(self._build_tank_plan(slots, batches, history))
        if other:
            other_block = QWidget()
            other_layout = QVBoxLayout(other_block); other_layout.setContentsMargins(0, 0, 0, 0); other_layout.setSpacing(5)
            other_layout.addWidget(_section("OTHER TANKS"))
            other_grid = QGridLayout(); other_grid.setSpacing(10)
            for index, tank in enumerate(other):
                self._add_tank_card(other_grid, tank, index // 4, index % 4, batches, history, "other")
            other_layout.addLayout(other_grid)
            self.arrangement_layout.addWidget(other_block)
        self._sync_tank_strip_geometry()
        # A visible QScrollArea may finish its child-layout negotiation on the next event turn.
        QTimer.singleShot(0, self._sync_tank_strip_geometry)
        self._populate_history(history)

    def _sync_tank_strip_geometry(self) -> None:
        """Publish the dynamically populated strip geometry to its non-resizable scroll area."""
        self.strip_content.ensurePolished()
        self.arrangement_layout.invalidate()
        self.arrangement_layout.activate()
        layout_size = self.arrangement_layout.sizeHint().expandedTo(self.arrangement_layout.minimumSize())
        content_size = self.strip_content.sizeHint().expandedTo(layout_size)
        content_size = QSize(max(1, content_size.width()), max(1, content_size.height()))
        self.strip_content.setFixedSize(content_size)
        self.strip_content.updateGeometry()
        self.strip_content.update()
        scrollbar_height = self.tank_strip.horizontalScrollBar().sizeHint().height()
        self.tank_strip.setFixedHeight(max(282, content_size.height() + scrollbar_height + 4))
        self.tank_strip.updateGeometry()
        self.tank_strip.viewport().update()

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
        card = TankCard(tank, batch.fuel_type if batch else None, batch.batch_name if batch else None, latest, kind)
        card.selected.connect(self._select_tank); card.activated.connect(self._show_tank_details)
        if isinstance(layout, QGridLayout):
            layout.addWidget(card, row, column)
        else:
            layout.addWidget(card)
        self.tank_cards.append(card)
        for sounding in self._fuel_tank_service.list_sounding_history(tank.id):
            sounding_batch = batches.get(sounding.fuel_batch_id) or batch
            history.append((tank, sounding, sounding_batch.fuel_type if sounding_batch else None))

    def _populate_history(self, history: list[tuple[FuelTank, TankSounding, str | None]]) -> None:
        history.sort(key=lambda item: (item[1].effective_at_utc, item[1].id or 0), reverse=True)
        for row, (tank, sounding, fuel_type) in enumerate(history[:20]):
            self.history_table.insertRow(row)
            values = (_format_utc(sounding.effective_at_utc), tank.name, sounding.reading_type, f"{sounding.reading_cm:.2f}", f"{sounding.trim_m:.2f}", "" if sounding.temperature_c is None else f"{sounding.temperature_c:.1f}", f"{sounding.calculated_volume_m3:.2f}", f"{sounding.manual_vcf:.5f}" if sounding.manual_vcf is not None else "--", f"{sounding.standard_volume_15_m3:.2f}" if sounding.standard_volume_15_m3 is not None else "--", f"{sounding.calculated_mass_mt:.2f}" if sounding.calculated_mass_mt is not None else "--", fuel_type or "")
            for column, value in enumerate(values): self.history_table.setItem(row, column, QTableWidgetItem(value))
        self.history_empty_label.setVisible(not history)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None: item.widget().deleteLater()
            elif item.layout() is not None: self._clear_layout(item.layout())

    def _select_tank(self, tank_id: int) -> None:
        self._selected_tank_id = tank_id; self.edit_tank_button.setEnabled(True); self.update_rob_button.setEnabled(True); self.calibration_button.setEnabled(True); self.fuel_batch_button.setEnabled(True)
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
        if self._tank_forecast_service is not None:
            try:
                forecast = next((item for item in self._tank_forecast_service.predict_tank_rob_at(tank.vessel_id, datetime.now(timezone.utc)) if item.tank_id == tank_id), None)
                predicted = forecast.predicted_mass_mt if forecast else None
            except Exception:
                predicted = None
        TankDetailsDialog(self._fuel_tank_service, tank, batch.fuel_type if batch else None, batch.batch_name if batch else None, self._fuel_tank_service.get_latest_sounding(tank_id), self, self.refresh, predicted).exec()


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


def _card_value(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-size: 7pt;")
    return label


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
