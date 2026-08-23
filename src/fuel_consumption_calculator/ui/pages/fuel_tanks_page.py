from __future__ import annotations

import re
from datetime import datetime

from PySide6.QtCore import QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from fuel_consumption_calculator.domain.fuel_tank import FUEL_TANK_TYPES, FuelTank, TankSounding
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService
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
        marker = QLabel(fuel_type or "FUEL --")
        marker.setStyleSheet(f"color: {FUEL_COLORS.get(fuel_type, '#8caabd')}; font-weight: 700; font-size: 7pt;")
        details.addWidget(marker)
        if batch_name and (kind in {"deep", "overflow"} or len(batch_name) <= 8):
            batch = _muted(_short_batch_name(batch_name))
            batch.setStyleSheet("font-size: 7pt;")
            batch.setToolTip(batch_name)
            details.addWidget(batch)
        if latest is None:
            details.addWidget(_card_value("ROB --"))
        else:
            if latest.calculated_mass_mt is not None:
                details.addWidget(_card_value(f"{latest.calculated_mass_mt:.0f} MT"))
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
        if self._tank_id is not None:
            self.activated.emit(self._tank_id)
        super().mouseDoubleClickEvent(event)


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


class TankDetailsDialog(QDialog):
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


class FuelTanksPage(QWidget):
    def __init__(self, vessel_service: VesselService, fuel_tank_service: FuelTankService) -> None:
        super().__init__()
        self._vessel_service, self._fuel_tank_service = vessel_service, fuel_tank_service
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
        self.update_rob_button = QPushButton("Update ROB"); self.update_rob_button.setEnabled(False); self.update_rob_button.clicked.connect(self._update_rob)
        self.calibration_button = QPushButton("Calibration"); self.calibration_button.setEnabled(False); self.calibration_button.clicked.connect(self._open_calibration)
        self.edit_tank_button = QPushButton("Edit Selected Tank"); self.edit_tank_button.setEnabled(False); self.edit_tank_button.clicked.connect(self._edit_selected_tank)
        actions.addWidget(self.add_tank_button); actions.addWidget(self.load_tank_set_button); actions.addWidget(self.edit_tank_button); actions.addWidget(self.update_rob_button); actions.addWidget(self.calibration_button); actions.addStretch(); layout.addLayout(actions)
        recent_title = QLabel("RECENT SOUNDINGS / ROB HISTORY"); recent_title.setObjectName("sectionTitle"); layout.addWidget(recent_title)
        self.history_table = QTableWidget(0, 8); self.history_table.setHorizontalHeaderLabels(("UTC", "Tank", "Type", "Reading", "Trim", "Temperature", "Volume m³", "Fuel"))
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.history_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection); self.history_table.setAlternatingRowColors(True)
        self.history_table.horizontalHeader().setStretchLastSection(True); self.history_table.setMinimumHeight(190); layout.addWidget(self.history_table)
        self.history_empty_label = _muted("No tank soundings recorded."); layout.addWidget(self.history_empty_label); layout.addStretch()
        scroll.setWidget(content); root.addWidget(scroll)

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        self._selected_tank_id = None; self.tank_cards = []; self.edit_tank_button.setEnabled(False); self.update_rob_button.setEnabled(False); self.calibration_button.setEnabled(False); self._clear_layout(self.arrangement_layout); self.history_table.setRowCount(0)
        if vessel is None:
            self.vessel_label.setText("Vessel: Not configured"); self.empty_label.setText("Configure a vessel before adding fuel oil tanks.")
            self.empty_label.show(); self.arrangement_panel.hide(); self.add_tank_button.setEnabled(False); self.load_tank_set_button.setEnabled(False); self.history_empty_label.show(); return
        self.vessel_label.setText(f"Vessel: {vessel.name}"); self.add_tank_button.setEnabled(True); self.load_tank_set_button.setEnabled(True)
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
            values = (_format_utc(sounding.effective_at_utc), tank.name, sounding.reading_type, f"{sounding.reading_cm:.2f}", f"{sounding.trim_m:.2f}", "" if sounding.temperature_c is None else f"{sounding.temperature_c:.1f}", f"{sounding.calculated_volume_m3:.2f}", fuel_type or "")
            for column, value in enumerate(values): self.history_table.setItem(row, column, QTableWidgetItem(value))
        self.history_empty_label.setVisible(not history)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None: item.widget().deleteLater()
            elif item.layout() is not None: self._clear_layout(item.layout())

    def _select_tank(self, tank_id: int) -> None:
        self._selected_tank_id = tank_id; self.edit_tank_button.setEnabled(True); self.update_rob_button.setEnabled(True); self.calibration_button.setEnabled(True)
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

    def _show_tank_details(self, tank_id: int) -> None:
        tank = self._fuel_tank_service.get_tank(tank_id)
        if tank is None: return
        batch = self._fuel_tank_service.get_fuel_batch(tank.current_fuel_batch_id) if tank.current_fuel_batch_id else None
        TankDetailsDialog(self._fuel_tank_service, tank, batch.fuel_type if batch else None, batch.batch_name if batch else None, self._fuel_tank_service.get_latest_sounding(tank_id), self).exec()


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
