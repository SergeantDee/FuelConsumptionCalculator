from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService
from fuel_consumption_calculator.services.tank_forecast_service import TankForecastService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.ui.pages.fuel_tank_operational_dialogs import CalibrationDialog, UpdateTankROBDialog
from fuel_consumption_calculator.ui.pages.fuel_tanks_page import ConsumptionTanksDialog, FuelTank, InternalTransferDialog, TankDialog, TankFuelBatchDialog, VesselTankSetDialog, _format_utc, _position_for_tank, _short_display_name
from fuel_consumption_calculator.ui.widgets.fuel_display import FuelBadge, fuel_color
from fuel_consumption_calculator.ui_v2.components import AppCard, EmptyState, PrimaryButton, SecondaryButton
from fuel_consumption_calculator.ui_v2.dialogs.tank_sounding_survey import TankSoundingSurveyV2

MDO_SLOTS = ("MDO_1_SERV", "MDO_2_SERV", "MDO_1_STOR", "MDO_2_STOR")
SUPPORT_SLOTS = ("ULSFO_SETT", "ULSFO_SERV", "HFO_SERV", "HFO_SETT")
DEEP_SLOTS = ("DEEP_3P", "DEEP_2P", "DEEP_1P", "DEEP_3S", "DEEP_2S", "DEEP_1S")


class TankCardBase(QFrame):
    selected = Signal(int)
    def __init__(self, tank, batch, sounding, deep: bool = False, parent=None) -> None:
        super().__init__(parent); self.tank_id = tank.id; self._deep = deep; self.setObjectName("v2TankCard"); self.setCursor(Qt.CursorShape.PointingHandCursor)
        body = QVBoxLayout(self); body.setContentsMargins(10, 8, 10, 9); body.setSpacing(5)
        top = QHBoxLayout(); name = QLabel(_short_display_name(tank.name)); name.setObjectName("v2TankName"); name.setToolTip(tank.name); top.addWidget(name, 1); top.addWidget(FuelBadge(batch.fuel_type if batch else "UNASSIGNED")); body.addLayout(top)
        actual = sounding.calculated_mass_mt if sounding else None; fill = (sounding.calculated_volume_m3 / tank.capacity_m3 * 100) if sounding and tank.capacity_m3 else None
        label = QLabel("ACTUAL ROB" if deep else "ROB"); label.setObjectName("v2TankCaption"); body.addWidget(label)
        value = QLabel(f"{actual:.2f} MT" if actual is not None else "—"); value.setObjectName("v2TankValue"); body.addWidget(value)
        if deep:
            estimated = QLabel("ESTIMATED  —"); estimated.setObjectName("v2TankMeta"); body.addWidget(estimated)
        gauge_row = QHBoxLayout(); gauge_row.setSpacing(8); gauge = QProgressBar(); gauge.setObjectName("v2TankGauge"); gauge.setRange(0, 100); gauge.setTextVisible(False); gauge.setValue(round(max(0, min(100, fill))) if fill is not None else 0); gauge.setProperty("fuelColor", fuel_color(batch.fuel_type) if batch else "#778590"); gauge.setStyleSheet(f"QProgressBar::chunk {{ background: {fuel_color(batch.fuel_type) if batch else '#778590'}; border-radius: 4px; }}")
        if deep: gauge.setOrientation(Qt.Orientation.Vertical); gauge.setFixedSize(14, 86)
        gauge_row.addWidget(gauge, 1); percentage = QLabel(f"{fill:.0f}%" if fill is not None else "—"); percentage.setObjectName("v2TankMeta"); gauge_row.addWidget(percentage); body.addLayout(gauge_row)
        self.setMinimumHeight(150 if deep else 118)
    def set_selected(self, selected: bool) -> None: self.setProperty("selected", selected); self.style().unpolish(self); self.style().polish(self)
    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.tank_id); super().mousePressEvent(event)


class FuelOilTanksPageV2(QWidget):
    """New V2 tank workspace; all tank operations delegate to existing dialogs/services."""
    def __init__(self, vessel_service: VesselService, fuel_tank_service: FuelTankService, tank_forecast_service: TankForecastService | None = None, voyage_service=None) -> None:
        super().__init__(); self._vessel_service, self._fuel_tank_service = vessel_service, fuel_tank_service; self._tank_forecast_service, self._voyage_service = tank_forecast_service, voyage_service; self._selected_tank_id = None; self.tank_cards = []
        root = QVBoxLayout(self); root.setContentsMargins(24, 20, 24, 18); root.setSpacing(12)
        title = QLabel("Fuel Oil Tanks"); title.setObjectName("v2PageTitle"); subtitle = QLabel("Vessel fuel tank overview and ROB management."); subtitle.setObjectName("v2PageSubtitle"); self.vessel_label = QLabel("Vessel: Not configured"); self.vessel_label.setObjectName("v2CardMeta"); root.addWidget(title); root.addWidget(subtitle); root.addWidget(self.vessel_label)
        actions = QHBoxLayout(); actions.setSpacing(8)
        self.survey_button = PrimaryButton("Update Tank ROBs"); self.survey_button.clicked.connect(self._open_survey); actions.addWidget(self.survey_button)
        self.consumption_tanks_button = SecondaryButton("Consumption Tanks"); self.consumption_tanks_button.clicked.connect(self._configure_consumption_tanks); actions.addWidget(self.consumption_tanks_button)
        self.internal_transfer_button = SecondaryButton("Internal Transfer"); self.internal_transfer_button.clicked.connect(self._open_internal_transfer); actions.addWidget(self.internal_transfer_button)
        self.add_tank_button = SecondaryButton("Add Tank"); self.add_tank_button.clicked.connect(self._add_tank); actions.addWidget(self.add_tank_button)
        self.load_tank_set_button = SecondaryButton("Load Vessel Tank Set"); self.load_tank_set_button.clicked.connect(self._load_vessel_tank_set); actions.addWidget(self.load_tank_set_button); actions.addStretch(); root.addLayout(actions)
        self.empty_label = EmptyState(""); root.addWidget(self.empty_label)
        split = QSplitter(Qt.Orientation.Horizontal); split.setChildrenCollapsible(False)
        self.arrangement_card = AppCard("TANK ARRANGEMENT"); self.arrangement_layout = QVBoxLayout(); self.arrangement_layout.setContentsMargins(0, 0, 0, 0); self.arrangement_layout.setSpacing(10); self.arrangement_card.body.addLayout(self.arrangement_layout); split.addWidget(self.arrangement_card)
        self.inspector = AppCard("SELECTED TANK"); self.inspector.setMinimumWidth(275); self.inspector.setMaximumWidth(360); self._build_inspector(); split.addWidget(self.inspector); split.setSizes([860, 300]); root.addWidget(split, 1)
        history = AppCard("RECENT SOUNDINGS / ROB HISTORY"); self.history_table = QTableWidget(0, 11); self.history_table.setObjectName("v2HistoryTable"); self.history_table.setHorizontalHeaderLabels(("UTC", "Tank", "Type", "Reading", "Trim", "Temp °C", "Observed m³", "VCF", "Volume @15°C", "MT", "Fuel")); self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.history_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection); self.history_table.verticalHeader().setVisible(False); self.history_table.verticalHeader().setDefaultSectionSize(30); self.history_table.setMaximumHeight(205)
        header = self.history_table.horizontalHeader()
        for column in (0, 2, 3, 4, 5, 6, 7, 8, 9, 10): header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        history.body.addWidget(self.history_table); self.history_empty_label = EmptyState("No tank soundings recorded."); history.body.addWidget(self.history_empty_label); history.setMaximumHeight(280); root.addWidget(history)
        self.refresh()

    def _build_inspector(self) -> None:
        self.inspector_empty = QWidget(); empty = QVBoxLayout(self.inspector_empty); empty.setContentsMargins(0, 22, 0, 12); empty.setSpacing(8)
        icon = QLabel("▣"); icon.setObjectName("v2InspectorEmptyIcon"); icon.setAlignment(Qt.AlignmentFlag.AlignCenter); empty.addWidget(icon)
        empty_title = QLabel("No tank selected"); empty_title.setObjectName("v2InspectorEmptyTitle"); empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter); empty.addWidget(empty_title)
        empty_hint = QLabel("Select a tank from the arrangement\nto view details and update ROBs."); empty_hint.setObjectName("v2CardMeta"); empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter); empty.addWidget(empty_hint); self.inspector.body.addWidget(self.inspector_empty)
        self.inspector_details = QWidget(); details = QVBoxLayout(self.inspector_details); details.setContentsMargins(0, 0, 0, 0); details.setSpacing(5)
        self.inspector_name = QLabel("Select a tank"); self.inspector_name.setObjectName("v2VesselName"); self.inspector_hint = QLabel("Choose a tank in the arrangement to view details."); self.inspector_hint.setObjectName("v2CardMeta"); self.inspector_fuel = FuelBadge("UNASSIGNED"); details.addWidget(self.inspector_name); details.addWidget(self.inspector_hint); details.addWidget(self.inspector_fuel, alignment=Qt.AlignmentFlag.AlignLeft)
        self.inspector_values = {}
        for caption in ("Actual ROB", "Estimated ROB", "Fill", "Estimated Empty", "Current Batch", "Density", "Last Sounding"):
            label = QLabel(caption.upper()); label.setObjectName("v2TankCaption"); value = QLabel("—"); value.setObjectName("v2InspectorValue"); details.addWidget(label); details.addWidget(value); self.inspector_values[caption] = value
        self.inspector.body.addWidget(self.inspector_details)
        self.action_buttons = []
        grid = QGridLayout(); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(8)
        for index, (text, callback) in enumerate((("Edit Tank", self._edit_selected_tank), ("Update ROB", self._update_rob), ("Calibration", self._open_calibration), ("Fuel / Batch", self._open_fuel_batch))):
            button = SecondaryButton(text); button.setEnabled(False); button.clicked.connect(callback); grid.addWidget(button, index // 2, index % 2); self.action_buttons.append(button)
        self.inspector.body.addStretch(); self.inspector.body.addLayout(grid)

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel(); self._selected_tank_id = None; self._clear_layout(self.arrangement_layout); self.history_table.setRowCount(0); self.tank_cards = []; self._clear_inspector()
        for button in (self.survey_button, self.consumption_tanks_button, self.internal_transfer_button, self.add_tank_button, self.load_tank_set_button): button.setEnabled(vessel is not None)
        if vessel is None: self.vessel_label.setText("Vessel: Not configured"); self.empty_label.setText("Configure a vessel before adding fuel oil tanks."); self.empty_label.show(); self.arrangement_card.hide(); self.history_empty_label.show(); return
        self.vessel_label.setText(f"Vessel: {vessel.name}"); tanks = self._fuel_tank_service.list_tanks(vessel.id)
        if not tanks: self.empty_label.setText("No fuel oil tanks configured. Load Vessel Tank Set or Add Tank to get started."); self.empty_label.show(); self.arrangement_card.hide(); self.history_empty_label.show(); return
        self.empty_label.hide(); self.arrangement_card.show(); batches = {batch.id: batch for batch in self._fuel_tank_service.list_fuel_batches(vessel.id)}; slots, other, history = {}, [], []
        for tank in tanks:
            position = _position_for_tank(tank.name)
            (slots if position and position not in slots else other).update({position: tank}) if position and position not in slots else other.append(tank)
        orientation = QLabel("AFT   →   FORWARD"); orientation.setObjectName("v2Orientation"); self.arrangement_layout.addWidget(orientation)
        groups = QGridLayout(); groups.setHorizontalSpacing(12); groups.setVerticalSpacing(12)
        self._add_group(groups, 0, 0, "MDO", MDO_SLOTS, slots, batches, history, False); self._add_group(groups, 0, 1, "SETTLING / SERVICE", SUPPORT_SLOTS, slots, batches, history, False); self._add_group(groups, 0, 2, "DEEP TANKS", DEEP_SLOTS, slots, batches, history, True)
        if other: self._add_group(groups, 1, 0, "OVERFLOW / OTHER", (), {}, batches, history, False, other)
        for col in range(3): groups.setColumnStretch(col, 1)
        self.arrangement_layout.addLayout(groups); self._populate_history(history)

    def _add_group(self, grid, row, column, title, positions, slots, batches, history, deep, supplied=None) -> None:
        holder = QWidget(); layout = QVBoxLayout(holder); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(7); heading = QLabel(title); heading.setObjectName("v2TankGroupHeading"); layout.addWidget(heading); cards = QGridLayout(); cards.setSpacing(8)
        tanks = supplied if supplied is not None else [slots[position] for position in positions if position in slots]
        for index, tank in enumerate(tanks): self._add_card(cards, index // (2 if deep else 1), index % (2 if deep else 1), tank, batches, history, deep)
        layout.addLayout(cards); layout.addStretch(); grid.addWidget(holder, row, column)

    def _add_card(self, layout, row, column, tank, batches, history, deep) -> None:
        batch = batches.get(tank.current_fuel_batch_id); sounding = self._fuel_tank_service.get_latest_sounding(tank.id); card = TankCardBase(tank, batch, sounding, deep); card.selected.connect(self._select_tank); layout.addWidget(card, row, column); self.tank_cards.append(card)
        for item in self._fuel_tank_service.list_sounding_history(tank.id): history.append((tank, item, batches.get(item.fuel_batch_id) or batch))

    def _select_tank(self, tank_id: int) -> None:
        self._selected_tank_id = tank_id
        for card in self.tank_cards: card.set_selected(card.tank_id == tank_id)
        for button in self.action_buttons: button.setEnabled(True)
        tank = self._fuel_tank_service.get_tank(tank_id); batch = self._fuel_tank_service.get_fuel_batch(tank.current_fuel_batch_id) if tank and tank.current_fuel_batch_id else None; sounding = self._fuel_tank_service.get_latest_sounding(tank_id) if tank else None
        if not tank: self._clear_inspector(); return
        fill = sounding.calculated_volume_m3 / tank.capacity_m3 * 100 if sounding and tank.capacity_m3 else None
        predicted, empty_text = None, "—"
        if self._tank_forecast_service is not None:
            try:
                now = datetime.now(timezone.utc)
                forecast = next((item for item in self._tank_forecast_service.predict_tank_rob_at(tank.vessel_id, now) if item.tank_id == tank_id), None)
                predicted = forecast.predicted_mass_mt if forecast else None
                empty = next((item for item in self._tank_forecast_service.predict_tank_empty_times(tank.vessel_id, now) if item.tank_id == tank_id), None)
                if empty is not None: empty_text = _format_utc(empty.estimated_empty_at_utc.isoformat()) if empty.estimated_empty_at_utc else (empty.issue or empty.state)
            except Exception:
                predicted, empty_text = None, "—"
        self.inspector_empty.hide(); self.inspector_details.show(); self.inspector_name.setText(tank.name); self.inspector_hint.hide(); self.inspector_fuel.set_fuel_type(batch.fuel_type if batch else "UNASSIGNED")
        values = {"Actual ROB": f"{sounding.calculated_mass_mt:.2f} MT" if sounding and sounding.calculated_mass_mt is not None else "—", "Estimated ROB": f"{predicted:.2f} MT" if predicted is not None else "—", "Fill": f"{fill:.1f}%" if fill is not None else "—", "Estimated Empty": empty_text, "Current Batch": batch.batch_name if batch else "—", "Density": f"{batch.density_15_kg_m3:g} kg/m³" if batch else "—", "Last Sounding": _format_utc(sounding.effective_at_utc) if sounding else "—"}
        for key, value in values.items(): self.inspector_values[key].setText(value)

    def _clear_inspector(self) -> None:
        self.inspector_empty.show(); self.inspector_details.hide(); self.inspector_name.setText("Select a tank"); self.inspector_hint.show(); self.inspector_fuel.set_fuel_type("UNASSIGNED")
        for value in self.inspector_values.values(): value.setText("—")
        for button in self.action_buttons: button.setEnabled(False)

    def _populate_history(self, history) -> None:
        history.sort(key=lambda item: (item[1].effective_at_utc, item[1].id or 0), reverse=True)
        for row, (tank, sounding, batch) in enumerate(history[:20]):
            self.history_table.insertRow(row); values = (_format_utc(sounding.effective_at_utc), tank.name, sounding.reading_type, f"{sounding.reading_cm:.2f}", f"{sounding.trim_m:.2f}", "—" if sounding.temperature_c is None else f"{sounding.temperature_c:.1f}", f"{sounding.calculated_volume_m3:.2f}", "—" if sounding.manual_vcf is None else f"{sounding.manual_vcf:.5f}", "—" if sounding.standard_volume_15_m3 is None else f"{sounding.standard_volume_15_m3:.2f}", "—" if sounding.calculated_mass_mt is None else f"{sounding.calculated_mass_mt:.2f}", batch.fuel_type if batch else "—")
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {3,4,5,6,7,8,9}: item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.history_table.setItem(row, column, item)
        self.history_empty_label.setVisible(not history)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            elif item.layout(): self._clear_layout(item.layout())
    def _vessel(self): return self._vessel_service.get_active_vessel()
    def _add_tank(self) -> None:
        vessel = self._vessel()
        if vessel and TankDialog(self._fuel_tank_service, vessel.id, parent=self).exec(): self.refresh()
    def _load_vessel_tank_set(self) -> None:
        vessel = self._vessel()
        if vessel: VesselTankSetDialog(self._fuel_tank_service, vessel.id, self).exec(); self.refresh()
    def _configure_consumption_tanks(self) -> None:
        vessel = self._vessel()
        if vessel and ConsumptionTanksDialog(self._fuel_tank_service, vessel.id, self).exec(): self.refresh()
    def _open_internal_transfer(self) -> None:
        vessel = self._vessel()
        if vessel and InternalTransferDialog(self._fuel_tank_service, vessel.id, self).exec(): self.refresh()
    def _open_survey(self) -> None:
        vessel = self._vessel()
        if vessel and TankSoundingSurveyV2(self._fuel_tank_service, vessel.id, self, self._voyage_service).exec(): self.refresh()
    def _selected_tank(self): return self._fuel_tank_service.get_tank(self._selected_tank_id) if self._selected_tank_id is not None else None
    def _edit_selected_tank(self) -> None:
        tank = self._selected_tank()
        if tank and TankDialog(self._fuel_tank_service, tank.vessel_id, tank, self).exec(): self.refresh()
    def _update_rob(self) -> None:
        tank = self._selected_tank()
        if tank and UpdateTankROBDialog(self._fuel_tank_service, tank, self).exec(): self.refresh()
    def _open_calibration(self) -> None:
        tank = self._selected_tank()
        if tank and CalibrationDialog(self._fuel_tank_service, tank, self).exec(): self.refresh()
    def _open_fuel_batch(self) -> None:
        tank = self._selected_tank()
        if tank: TankFuelBatchDialog(self._fuel_tank_service, tank, self.refresh, self).exec()
