from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from fuel_consumption_calculator.calculations.bunker_projection_engine import EventBunkerROBProjection
from fuel_consumption_calculator.domain.bunker import BunkerLiftLimit, BunkerPlanStatus
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.services.bunker_service import BunkerService
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.rob_service import ROBService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.vessel_service import VesselService
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
            if rob_values[{1: 0, 3: 1, 4: 2, 6: 3, 7: 4, 9: 5}[index.column()]] < 0:
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


class BunkerPage(QWidget):
    def __init__(
        self,
        vessel_service: VesselService,
        bunker_service: BunkerService,
        schedule_service: ScheduleService,
        consumption_service: ConsumptionService,
        rob_service: ROBService,
    ) -> None:
        super().__init__()
        self._vessel_service = vessel_service
        self._bunker_service = bunker_service
        self._schedule_service = schedule_service
        self._consumption_service = consumption_service
        self._rob_service = rob_service
        self._events: list[ScheduleEvent] = []
        self._last_projection_rows: list[EventBunkerROBProjection] = []
        self._capacity_inputs: dict[str, QDoubleSpinBox] = {}
        self._target_inputs: dict[str, QDoubleSpinBox] = {}
        self._planned_inputs: dict[str, QDoubleSpinBox] = {}
        self._target_rob_labels: dict[str, QLabel] = {}
        self._arrival_rob_labels: dict[str, QLabel] = {}
        self._max_lift_labels: dict[str, QLabel] = {}
        self._lift_limits: dict[str, BunkerLiftLimit] = {}
        self._loading_plan = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)
        layout.addWidget(PageHeader("Bunker Planner", "Plan bunker lifts after arrival and before port consumption."))

        self.vessel_label = QLabel("Vessel: Not configured")
        self.vessel_label.setObjectName("fieldLabel")
        layout.addWidget(self.vessel_label)

        capacity_panel = QFrame()
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
        layout.addWidget(capacity_panel)

        plan_panel = QFrame()
        plan_panel.setObjectName("panel")
        plan_layout = QVBoxLayout(plan_panel)
        plan_layout.setContentsMargins(18, 16, 18, 16)
        plan_layout.addWidget(QLabel("PLANNED BUNKER PORT"))
        self.event_combo = QComboBox()
        self.event_combo.currentIndexChanged.connect(self._selection_changed)
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
        self.clear_plan_button = QPushButton("Clear Bunker Plan")
        self.clear_plan_button.setObjectName("dangerButton")
        self.clear_plan_button.clicked.connect(self._clear_plan)
        actions.addWidget(self.save_plan_button)
        actions.addWidget(self.confirm_plan_button)
        actions.addWidget(self.use_max_button)
        actions.addWidget(self.clear_plan_button)
        actions.addStretch()
        plan_layout.addLayout(actions)
        layout.addWidget(plan_panel)

        self.plans_model = BunkerPlansTableModel()
        self.plans_table = QTableView()
        self.plans_table.setModel(self.plans_model)
        self.plans_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.plans_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.plans_table.verticalHeader().setDefaultSectionSize(32)
        self.plans_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(QLabel("CURRENT BUNKER PLANS"))
        layout.addWidget(self.plans_table)

        self.projection_model = BunkerProjectionTableModel()
        self.projection_table = QTableView()
        self.projection_table.setModel(self.projection_model)
        self.projection_table.verticalHeader().setDefaultSectionSize(32)
        self.projection_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.projection_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(QLabel("PROJECTED ROB WITH PLANNED BUNKERS"))
        layout.addWidget(self.projection_table, 1)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("mutedText")
        layout.addWidget(self.status_label)
        self.refresh()

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self.vessel_label.setText("Vessel: Not configured")
            self._set_controls_enabled(False)
            return
        self.vessel_label.setText(f"Vessel: {vessel.name}  |  IMO {vessel.imo}")
        self._set_controls_enabled(True)
        self._events = self._schedule_service.list_events(vessel.id)
        self._load_capacities(vessel.id)
        self._populate_events()
        self._refresh_projection(vessel.id)
        self._selection_changed()
        self.status_label.setText("Bunker planner loaded." if self._events else "No schedule events available.")

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
            plan = self._bunker_service.build_plan(vessel_id=vessel.id, event=event, quantities=quantities, lift_limits=self._lift_limits)
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

    def _refresh_projection(self, vessel_id: int) -> None:
        plan_statuses = self._bunker_service.list_plan_statuses(vessel_id, self._events)
        self.plans_model.set_rows(plan_statuses)
        timeline = self._schedule_service.get_timeline(vessel_id)
        if not timeline.rows:
            self.projection_model.set_rows([])
            self._last_projection_rows = []
            return
        try:
            consumption = self._consumption_service.calculate_schedule_consumption(vessel_id, timeline)
            starting_rob = self._rob_service.load_starting_rob(vessel_id)
            projection = self._bunker_service.project_schedule_rob_with_bunkers(
                starting_rob=starting_rob,
                consumption=consumption,
                active_bunker_plans=[status.plan for status in plan_statuses if status.status == "CONFIRMED"],
            )
        except Exception as exc:
            self.projection_model.set_rows([])
            self._last_projection_rows = []
            self.status_label.setText(str(exc))
            return
        self._last_projection_rows = projection.rows
        self.projection_model.set_rows(projection.rows)

    def _update_lift_limits(self) -> None:
        event = self._selected_event()
        if event is None:
            return
        projection_row = next((row for row in self._last_projection_rows if row.sequence_number == event.sequence_number), None)
        arrival_rob = projection_row.arrival_rob_mt if projection_row else {fuel_type: 0.0 for fuel_type in FUEL_TYPES}
        profile = self._bunker_service.build_capacity_profile(
            self._vessel_service.get_active_vessel().id if self._vessel_service.get_active_vessel() else 0,
            {fuel_type: (self._capacity_inputs[fuel_type].value(), self._target_inputs[fuel_type].value()) for fuel_type in FUEL_TYPES},
        )
        self._lift_limits = self._bunker_service.calculate_lift_limits(
            profile,
            arrival_rob,
            {fuel_type: self._target_inputs[fuel_type].value() for fuel_type in FUEL_TYPES},
        )
        for fuel_type, limit in self._lift_limits.items():
            getattr(self, f"_{fuel_type.lower()}_capacity_label").setText(_format_mt(limit.capacity_mt))
            getattr(self, f"_{fuel_type.lower()}_target_label").setText(f"{limit.target_fill_percent:.2f} %")
            self._target_rob_labels[fuel_type].setText(_format_mt(limit.target_rob_mt))
            self._arrival_rob_labels[fuel_type].setText(_format_mt(limit.arrival_rob_mt))
            self._max_lift_labels[fuel_type].setText(_format_mt(limit.max_lift_mt))
            self._planned_inputs[fuel_type].setMaximum(limit.max_lift_mt)

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
        arrival_snapshot = event.arrival_at.isoformat(timespec="minutes")
        for status in self._bunker_service.list_plan_statuses(vessel_id, self._events):
            if (
                status.plan.sequence_number == event.sequence_number
                and status.plan.port_snapshot == event.port
                and status.plan.arrival_snapshot == arrival_snapshot
            ):
                return status
        return None

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


def _format_mt(value: float) -> str:
    return f"{value:.2f} MT"
