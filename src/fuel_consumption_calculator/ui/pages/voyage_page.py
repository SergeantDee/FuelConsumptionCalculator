from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.voyage import ActualROBObservation, CalculatedVoyageLeg, FuelChangeoverEvent, MACHINERY_TYPES, MachineryFuelState
from fuel_consumption_calculator.domain.voyage_stages import (
    STAGE_ARRIVAL_MANEUVERING,
    STAGE_DEPARTURE_MANEUVERING,
    STAGE_PORT_STAY,
    STAGE_SEA_PASSAGE,
    OperationalStage,
    VoyageStageTimeline,
    build_voyage_stage_timeline,
)
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.rob_service import ROBService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.settings_service import SettingsService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.services.voyage_service import VoyageService
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader
from fuel_consumption_calculator.ui.widgets.actual_rob_dialog import ActualROBDialog


@dataclass(frozen=True, slots=True)
class PlannerDisplayRow:
    stage: OperationalStage | None = None
    changeovers: tuple[FuelChangeoverEvent, ...] = ()

    @property
    def timestamp(self) -> datetime | None:
        if self.stage is not None:
            return self.stage.start_utc
        return self.changeovers[0].effective_at_utc if self.changeovers else None


def build_planner_display_rows(
    stages: list[OperationalStage],
    changeovers: tuple[FuelChangeoverEvent, ...],
) -> list[PlannerDisplayRow]:
    grouped: dict[datetime, list[FuelChangeoverEvent]] = {}
    for event in changeovers:
        timestamp = _as_naive_utc(event.effective_at_utc)
        if timestamp is not None:
            grouped.setdefault(timestamp, []).append(event)
    rows = [PlannerDisplayRow(stage=stage) for stage in stages]
    rows.extend(PlannerDisplayRow(changeovers=tuple(events)) for _, events in sorted(grouped.items()))
    return sorted(rows, key=lambda row: (_as_naive_utc(row.timestamp) or datetime.max, 0 if row.stage is not None else 1))


class VoyagePage(QWidget):
    COLUMN_LAYOUT_SETTING = "voyage_planner_column_layout"
    EVENT_COLUMN = 1
    DEFAULT_HIDDEN_COLUMNS = frozenset({2, 8, 9, 10, 13})
    TABLE_COLUMNS = (
        "Status", "Event", "Stage", "Start UTC", "End UTC", "Duration",
        "Distance", "Calculated Speed", "RPM", "ME Load", "DG Load", "Total Consumption",
        "EOE ROB", "ROB Update",
        "Issue",
    )

    def __init__(
        self,
        vessel_service: VesselService,
        schedule_service: ScheduleService,
        consumption_service: ConsumptionService,
        voyage_service: VoyageService,
        rob_service: ROBService,
        settings_service: SettingsService,
    ) -> None:
        super().__init__()
        self._vessel_service = vessel_service
        self._schedule_service = schedule_service
        self._consumption_service = consumption_service
        self._voyage_service = voyage_service
        self._rob_service = rob_service
        self._settings_service = settings_service
        self._restoring_column_layout = True
        self._timeline: VoyageStageTimeline | None = None
        self._active_fuel_state: MachineryFuelState | None = None
        self._energy_config = None
        self._fuel_changeovers: tuple[FuelChangeoverEvent, ...] = ()
        self._rob_observations: tuple[ActualROBObservation, ...] = ()
        self._display_rows: list[PlannerDisplayRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)
        layout.addWidget(PageHeader("Voyage Planner", "Chronological operational stages. Double-click a row for event details."))

        self.summary_panel = QFrame()
        self.summary_panel.setObjectName("panel")
        summary_grid = QGridLayout(self.summary_panel)
        summary_grid.setContentsMargins(18, 16, 18, 16)
        summary_grid.setHorizontalSpacing(18)
        self.vessel_label = QLabel("Vessel: Not configured")
        self.current_stage_label = QLabel("Current Stage: -")
        self.next_port_label = QLabel("Next Port: -")
        self.next_event_label = QLabel("Next Major Event: -")
        self.summary_rob_label = QLabel("Current Predicted ROB: ULSFO 0.0 MT  |  VLSFO 0.0 MT  |  MDO 0.0 MT")
        for label in (self.vessel_label, self.current_stage_label, self.next_port_label, self.next_event_label):
            label.setObjectName("fieldLabel")
        self.summary_rob_label.setObjectName("mutedText")
        summary_grid.addWidget(self.vessel_label, 0, 0)
        summary_grid.addWidget(self.current_stage_label, 0, 1)
        summary_grid.addWidget(self.next_port_label, 1, 0)
        summary_grid.addWidget(self.next_event_label, 1, 1)
        summary_grid.addWidget(self.summary_rob_label, 2, 0, 1, 2)
        layout.addWidget(self.summary_panel)

        self.empty_state = QLabel("No voyage stages available. Save at least two resolved schedule events with a departure to build a voyage timeline.")
        self.empty_state.setObjectName("emptyState")
        self.empty_state.setWordWrap(True)
        layout.addWidget(self.empty_state)

        actions = QHBoxLayout()
        self.add_operational_event_button = QPushButton("Add Operational Event")
        self.add_operational_event_button.clicked.connect(self._add_operational_event)
        actions.addWidget(self.add_operational_event_button)
        actions.addStretch()
        layout.addLayout(actions)

        self.stage_table = QTableWidget(0, len(self.TABLE_COLUMNS))
        self.stage_table.setObjectName("voyageStageTable")
        self.stage_table.setHorizontalHeaderLabels(self.TABLE_COLUMNS)
        self.stage_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.stage_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.stage_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stage_table.setSortingEnabled(False)
        self.stage_table.setWordWrap(False)
        self.stage_table.verticalHeader().setVisible(False)
        header = self.stage_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionsMovable(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_column_menu)
        self._apply_default_column_layout()
        self.stage_table.setColumnWidth(14, 240)
        self.stage_table.setColumnWidth(16, 180)
        self.stage_table.cellDoubleClicked.connect(self._open_stage_details)
        layout.addWidget(self.stage_table, 1)

        self._restore_column_layout()
        self._restoring_column_layout = False
        header.sectionResized.connect(lambda *_: self._save_column_layout())
        header.sectionMoved.connect(lambda *_: self._save_column_layout())

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("mutedText")
        layout.addWidget(self.status_label)
        self.refresh()

    def refresh(self) -> None:
        self._clear_table()
        self._energy_config = None
        self._fuel_changeovers = ()
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self.vessel_label.setText("Vessel: Not configured")
            self.current_stage_label.setText("Current Stage: -")
            self.next_port_label.setText("Next Port: -")
            self.next_event_label.setText("Next Major Event: -")
            self.summary_rob_label.setText("Current Predicted ROB: ULSFO 0.0 MT  |  VLSFO 0.0 MT  |  MDO 0.0 MT")
            self.empty_state.setVisible(True)
            self.stage_table.setVisible(False)
            self.status_label.setText("Configure a vessel before planning voyage stages.")
            return

        events = self._schedule_service.list_events(vessel.id)
        schedule_timeline = self._schedule_service.get_timeline(vessel.id)
        if schedule_timeline.issues:
            self.empty_state.setVisible(True)
            self.stage_table.setVisible(False)
            self.status_label.setText(f"Schedule chronology warning: {schedule_timeline.issues[0].message}")
            return

        profile = self._consumption_service.load_profile(vessel.id)
        plan = self._voyage_service.calculate_plan(vessel.id, events, profile)
        voyage_result = self._voyage_service.calculate_consumption_for_plan(
            events=events,
            timeline=schedule_timeline,
            plan=plan,
            profile=profile,
        )
        starting_rob = self._rob_service.load_starting_rob(vessel.id)
        observations = self._voyage_service.list_actual_rob_observations(vessel.id)
        self._rob_observations = tuple(observations)
        self._timeline = build_voyage_stage_timeline(
            events,
            plan,
            starting_rob,
            port_breakdowns=voyage_result.port_breakdowns,
            rob_observations=observations,
        )
        self._active_fuel_state = plan.initial_fuel_state
        self._energy_config = plan.energy_config
        self._fuel_changeovers = plan.fuel_changeovers
        self._display_rows = build_planner_display_rows(self._timeline.stages, self._fuel_changeovers)

        self.vessel_label.setText(f"Vessel: {vessel.name}  |  IMO {vessel.imo}")
        current = self._timeline.current_stage
        self.current_stage_label.setText(f"Current Stage: {_current_stage_text(self._timeline)}")
        self.next_port_label.setText(f"Next Port: {self._timeline.next_port or '-'}")
        next_major = next((stage for stage in self._timeline.stages if stage.status != "COMPLETED"), None)
        self.next_event_label.setText(f"Next Major Event: {next_major.title if next_major else '-'}")
        self.summary_rob_label.setText("Current Predicted ROB: " + _fmt_fuel_line(self._timeline.current_predicted_rob_mt))

        self.empty_state.setVisible(len(self._timeline.stages) == 0)
        self.stage_table.setVisible(len(self._display_rows) > 0)
        self._populate_stage_table(self._display_rows)
        self.status_label.setText(f"Loaded {len(self._display_rows)} operational timeline events.")

    def _clear_table(self) -> None:
        self.stage_table.setRowCount(0)

    def _apply_default_column_layout(self) -> None:
        header = self.stage_table.horizontalHeader()
        for logical_index in range(len(self.TABLE_COLUMNS)):
            self.stage_table.setColumnHidden(logical_index, logical_index in self.DEFAULT_HIDDEN_COLUMNS)
            header.moveSection(header.visualIndex(logical_index), logical_index)
        widths = (92, 235, 150, 138, 138, 96, 100, 80, 76, 84, 84, 150, 165, 155, 220, 150, 180)
        for logical_index, width in enumerate(widths):
            self.stage_table.setColumnWidth(logical_index, width)

    def _show_column_menu(self, position) -> None:
        header = self.stage_table.horizontalHeader()
        menu = QMenu(header)
        columns_menu = menu.addMenu("Columns")
        for logical_index, label in enumerate(self.TABLE_COLUMNS):
            action = QAction(label, columns_menu)
            action.setCheckable(True)
            action.setChecked(not self.stage_table.isColumnHidden(logical_index))
            if logical_index == self.EVENT_COLUMN:
                action.setEnabled(False)
                action.setToolTip("Event is always visible.")
            else:
                action.toggled.connect(
                    lambda visible, column=logical_index: self._set_column_visible(column, visible)
                )
            columns_menu.addAction(action)
        menu.addSeparator()
        show_all = menu.addAction("Show All")
        show_all.triggered.connect(self._show_all_columns)
        reset = menu.addAction("Reset Column Layout")
        reset.triggered.connect(self._reset_column_layout)
        menu.exec(header.mapToGlobal(position))

    def _set_column_visible(self, column: int, visible: bool) -> None:
        if column == self.EVENT_COLUMN:
            return
        self.stage_table.setColumnHidden(column, not visible)
        self._save_column_layout()

    def _show_all_columns(self) -> None:
        for column in range(len(self.TABLE_COLUMNS)):
            self.stage_table.setColumnHidden(column, False)
        self._save_column_layout()

    def _reset_column_layout(self) -> None:
        self._restoring_column_layout = True
        self._apply_default_column_layout()
        self._restoring_column_layout = False
        self._save_column_layout()

    def _restore_column_layout(self) -> None:
        try:
            saved = self._settings_service.load().get(self.COLUMN_LAYOUT_SETTING)
        except RuntimeError:
            return
        if not isinstance(saved, dict):
            return
        column_count = len(self.TABLE_COLUMNS)
        order = saved.get("order")
        widths = saved.get("widths")
        hidden = saved.get("hidden")
        if not (
            isinstance(order, list)
            and sorted(order) == list(range(column_count))
            and isinstance(widths, list)
            and len(widths) == column_count
            and isinstance(hidden, list)
        ):
            return
        header = self.stage_table.horizontalHeader()
        for visual_index, logical_index in enumerate(order):
            header.moveSection(header.visualIndex(logical_index), visual_index)
        for logical_index, width in enumerate(widths):
            if isinstance(width, int) and width > 20:
                self.stage_table.setColumnWidth(logical_index, width)
        hidden_columns = {column for column in hidden if isinstance(column, int)}
        hidden_columns.discard(self.EVENT_COLUMN)
        for logical_index in range(column_count):
            self.stage_table.setColumnHidden(logical_index, logical_index in hidden_columns)

    def _save_column_layout(self) -> None:
        if self._restoring_column_layout:
            return
        try:
            settings = self._settings_service.load()
            header = self.stage_table.horizontalHeader()
            settings[self.COLUMN_LAYOUT_SETTING] = {
                "order": [header.logicalIndex(visual) for visual in range(len(self.TABLE_COLUMNS))],
                "widths": [self.stage_table.columnWidth(column) for column in range(len(self.TABLE_COLUMNS))],
                "hidden": [
                    column for column in range(len(self.TABLE_COLUMNS))
                    if self.stage_table.isColumnHidden(column) and column != self.EVENT_COLUMN
                ],
            }
            self._settings_service.save(settings)
        except RuntimeError:
            self.status_label.setText("Column layout could not be saved locally.")

    def _populate_stage_table(self, display_rows: list[PlannerDisplayRow]) -> None:
        self.stage_table.setRowCount(len(display_rows))
        for row, display_row in enumerate(display_rows):
            if display_row.stage is None:
                self._populate_changeover_row(row, display_row.changeovers)
                continue
            stage = display_row.stage
            leg = stage.leg
            values = (
                stage.status,
                stage.title,
                _stage_label(stage),
                _fmt_dt(stage.start_utc),
                _fmt_dt(stage.end_utc),
                _fmt_duration(_hours(stage.start_utc, stage.end_utc)),
                _stage_distance(stage),
                _fmt_kn(leg.required_speed_knots if stage.stage_type == STAGE_SEA_PASSAGE and leg else None),
                _fmt_rpm(leg.predicted_rpm if stage.stage_type == STAGE_SEA_PASSAGE and leg else None),
                _fmt_percent(leg.predicted_me_load_percent if stage.stage_type == STAGE_SEA_PASSAGE and leg else None),
                _stage_dg_load(stage),
                _fmt_fuel_line(stage.consumption_mt),
                _fmt_compact_rob(stage.rob.end_mt),
                _fmt_observation(self._latest_observation_for(stage)),
                _stage_issue(stage),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self._style_stage_item(item, stage.status)
                self.stage_table.setItem(row, column, item)
            self.stage_table.setRowHeight(row, 34)

    def _populate_changeover_row(self, row: int, changeovers: tuple[FuelChangeoverEvent, ...]) -> None:
        statuses = {"ACTUAL" if event.actual_at_utc is not None else "PLANNED" for event in changeovers}
        status = statuses.pop() if len(statuses) == 1 else "PARTIAL"
        by_machinery = {event.machinery: event for event in changeovers}
        values = (
            status,
            "Fuel Changeover",
            "Fuel Changeover",
            _fmt_dt(changeovers[0].effective_at_utc),
            *("-",) * 10, "",
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            self._style_stage_item(item, "COMPLETED" if status == "ACTUAL" else "PLANNED")
            self.stage_table.setItem(row, column, item)
        self.stage_table.setRowHeight(row, 34)

    def _open_changeover_details(self, changeovers: tuple[FuelChangeoverEvent, ...]) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            return
        dialog = ChangeoverDetailsDialog(changeovers, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.delete_requested:
            for event in changeovers:
                if event.id is not None:
                    self._voyage_service.delete_fuel_changeover(vessel.id, event.id)
        else:
            for event in dialog.events(vessel.id):
                self._voyage_service.save_fuel_changeover(event)
        self.refresh()

    def _add_operational_event(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            return
        dialog = NewChangeoverDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            for event in dialog.events(vessel.id):
                self._voyage_service.save_fuel_changeover(event)
        except Exception as exc:
            QMessageBox.warning(self, "Changeover not saved", str(exc))
            return
        self.refresh()

    @staticmethod
    def _style_stage_item(item: QTableWidgetItem, status: str) -> None:
        colors = {
            "CURRENT": (QColor("#123d50"), QColor("#ffffff")),
            "COMPLETED": (QColor("#1e2a30"), QColor("#8fa4ad")),
            "PLANNED": (QColor("#20343f"), QColor("#d7e4e9")),
        }
        background, foreground = colors.get(status, colors["PLANNED"])
        item.setBackground(background)
        item.setForeground(foreground)
        if status == "CURRENT":
            font = item.font()
            font.setBold(True)
            item.setFont(font)

    def _open_stage_details(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self._display_rows):
            return
        display_row = self._display_rows[row]
        if display_row.stage is None:
            self._open_changeover_details(display_row.changeovers)
            return
        stage = display_row.stage
        dialog = StageEditDialog(stage, self._latest_observation_for(stage), self)
        dialog.actual_rob_requested.connect(
            lambda selected=stage, details=dialog: self._update_actual_rob_from_details(details, selected)
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.actual_rob_updated:
            return
        values = dialog.values()
        if values:
            self._save_stage_values(stage, values)

    def _latest_observation_for(self, stage: OperationalStage) -> ActualROBObservation | None:
        end = _as_naive_utc(stage.end_utc) or datetime.max
        relevant = [
            observation for observation in self._rob_observations
            if (_as_naive_utc(observation.effective_at_utc) or datetime.min) <= end
        ]
        return max(relevant, key=lambda observation: _as_naive_utc(observation.effective_at_utc) or datetime.min, default=None)

    def _machinery_table_text(self, stage: OperationalStage, machinery: str) -> str:
        quantity = self._machinery_totals(stage).get(machinery)
        allocation = self._machinery_allocation(stage, machinery)
        if allocation is not None:
            parts = [
                f"{fuel} {float(allocation[fuel]):.2f}"
                for fuel in FUEL_TYPES
                if allocation.get(fuel) not in (None, 0.0)
            ]
            if parts:
                return " | ".join(parts) + " MT"
            if quantity == 0.0:
                return "0.00 MT"
        if quantity is None:
            return "-"
        fuel = self._fuel_display_for_stage(stage, machinery)
        return f"{quantity:.2f} MT" + (f" {fuel}" if fuel else "")

    def _machinery_allocation(self, stage: OperationalStage, machinery: str) -> dict[str, float | None] | None:
        if stage.stage_type == STAGE_PORT_STAY and stage.port_breakdown is not None:
            if machinery == "GENERATORS":
                return stage.port_breakdown.generator_consumed_mt
            if machinery == "AUX_BOILER":
                return stage.port_breakdown.boiler_consumed_mt
            return {fuel: 0.0 for fuel in FUEL_TYPES}
        if stage.stage_type != STAGE_SEA_PASSAGE or stage.leg is None:
            return None
        if machinery == "GENERATORS":
            return stage.leg.sea_generator_consumed_mt
        if machinery == "AUX_BOILER":
            return stage.leg.sea_boiler_consumed_mt
        generator = stage.leg.sea_generator_consumed_mt
        boiler = stage.leg.sea_boiler_consumed_mt
        if generator is None or boiler is None:
            return None
        return {
            fuel: _subtract_optional(stage.consumption_mt.get(fuel), generator.get(fuel), boiler.get(fuel))
            for fuel in FUEL_TYPES
        }

    def _machinery_fuel_for_table(self, stage: OperationalStage, machinery: str) -> str | None:
        allocation = self._machinery_allocation(stage, machinery)
        if allocation is not None:
            fuels = [fuel for fuel in FUEL_TYPES if allocation.get(fuel) not in (None, 0.0)]
            return fuels[0] if len(fuels) == 1 else None
        fuel = self._fuel_display_for_stage(stage, machinery)
        return fuel if fuel in FUEL_TYPES else None

    def _build_card(self, stage: OperationalStage) -> QFrame:
        card = QFrame()
        card.setObjectName(
            {"CURRENT": "voyageStageCurrent", "COMPLETED": "voyageStageCompleted"}.get(
                stage.status,
                "voyageStagePlanned",
            )
        )
        card.setMinimumWidth(1126)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)

        badge = QLabel(stage.status)
        badge.setObjectName(
            {
                "CURRENT": "stageBadgeCurrent",
                "COMPLETED": "stageBadgeCompleted",
            }.get(stage.status, "stageBadgePlanned")
        )

        title = QLabel(stage.title)
        title.setObjectName("sectionTitle")

        subtitle = QLabel(stage.subtitle)
        subtitle.setObjectName("mutedText")

        edit_button = QPushButton("Edit")
        edit_button.clicked.connect(
            lambda checked=False, selected=stage: self._edit_stage(selected)
        )
        edit_button.setEnabled(stage.leg is not None or stage.incoming_leg is not None)

        rob_button = QPushButton("Update Actual ROB")
        rob_button.clicked.connect(
            lambda checked=False, selected=stage: self._update_actual_rob(selected)
        )

        header.addWidget(badge)
        header.addWidget(title)
        header.addWidget(subtitle, 1)
        header.addWidget(edit_button)
        header.addWidget(rob_button)
        layout.addLayout(header)

        # Row 1: time + key operational data.
        layout.addWidget(self._compact_operational_row(stage))

        # Row 2: ME / DG / AB estimated consumption + end-of-event ROB.
        layout.addWidget(self._compact_fuel_row(stage))

        return card

    def _compact_operational_row(self, stage: OperationalStage) -> QWidget:
        frame = QWidget()
        grid = QGridLayout(frame)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)

        duration = _hours(stage.start_utc, stage.end_utc)

        if stage.stage_type == STAGE_PORT_STAY:
            breakdown = stage.port_breakdown
            metrics = (
                ("Start", _fmt_dt(stage.start_utc)),
                ("End", _fmt_dt(stage.end_utc)),
                ("Duration", _fmt_duration(duration)),
                ("Reefers", _fmt_number(breakdown.reefers if breakdown else None)),
                (
                    "Electrical Load",
                    _fmt_kw(breakdown.total_electrical_load_kw if breakdown else None),
                ),
                (
                    "DG Load",
                    _fmt_percent(breakdown.generator_load_percent if breakdown else None),
                ),
                (
                    "Ambient",
                    _fmt_c(_override_value_or_none(stage.leg, "port_ambient_c")),
                ),
            )

        elif stage.stage_type == STAGE_SEA_PASSAGE:
            leg = stage.leg
            metrics = (
                ("Start", _fmt_dt(stage.start_utc)),
                ("End", _fmt_dt(stage.end_utc)),
                ("Duration", _fmt_duration(duration)),
                ("Distance", _fmt_nm(leg.sea_distance_nm if leg else None)),
                ("Speed", _fmt_kn(leg.required_speed_knots if leg else None)),
                ("RPM", _fmt_rpm(leg.predicted_rpm if leg else None)),
                ("ME Load", _fmt_percent(leg.predicted_me_load_percent if leg else None)),
                (
                    "DG Load",
                    _fmt_percent(leg.sea_generator_load_percent if leg else None),
                ),
                ("EGB", _egb_label(leg)),
            )

        elif stage.stage_type == STAGE_DEPARTURE_MANEUVERING:
            metrics = (
                ("Start", _fmt_dt(stage.start_utc)),
                ("End", _fmt_dt(stage.end_utc)),
                ("Duration", _fmt_duration(duration)),
                (
                    "Pilot Distance",
                    _fmt_nm(_route_value(stage.leg, "departure_pilot_distance_nm")),
                ),
            )

        else:
            metrics = (
                ("Start", _fmt_dt(stage.start_utc)),
                ("End", _fmt_dt(stage.end_utc)),
                ("Duration", _fmt_duration(duration)),
                (
                    "Pilot Distance",
                    _fmt_nm(_route_value(stage.leg, "arrival_pilot_distance_nm")),
                ),
            )

        for column, (label_text, value_text) in enumerate(metrics):
            _add_metric(grid, 0, column, label_text, value_text)
            grid.setColumnStretch(column, 1)

        return frame

    def _compact_fuel_row(self, stage: OperationalStage) -> QWidget:
        frame = QWidget()
        grid = QGridLayout(frame)
        grid.setContentsMargins(0, 3, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(0)

        totals = self._machinery_totals(stage)

        for column, (machinery, short_name) in enumerate(
            (
                ("MAIN_ENGINE", "Main Engine"),
                ("GENERATORS", "Auxiliary Engines"),
                ("AUX_BOILER", "Auxiliary Boiler"),
            )
        ):
            block = self._machinery_block(
                short_name,
                totals[machinery],
                self._fuel_display_for_stage(stage, machinery),
            )
            grid.addWidget(block, 0, column)
            grid.setColumnStretch(column, 1)

        rob_block = QWidget()
        rob_layout = QVBoxLayout(rob_block)
        rob_layout.setContentsMargins(0, 0, 0, 0)
        rob_layout.setSpacing(2)

        rob_title = QLabel("End-of-Event ROB")
        rob_title.setObjectName("fieldLabel")

        rob_value = QLabel(_fmt_fuel_line(stage.rob.end_mt))
        rob_value.setObjectName("mutedText")
        rob_value.setWordWrap(False)

        rob_layout.addWidget(rob_title)
        rob_layout.addWidget(rob_value)

        grid.addWidget(rob_block, 0, 3)
        grid.setColumnStretch(3, 3)

        return frame

    def _machinery_block(
        self,
        title_text: str,
        quantity_mt: float | None,
        fuel_text: str | None,
    ) -> QWidget:
        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        title = QLabel(title_text)
        title.setObjectName("fieldLabel")

        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(6)

        value = QLabel(_fmt_mt(quantity_mt))
        value.setObjectName("mutedText")

        fuel = self._fuel_badge(fuel_text)

        value_row.addWidget(value)
        value_row.addWidget(fuel)
        value_row.addStretch()

        layout.addWidget(title)
        layout.addLayout(value_row)

        return block

    def _fuel_badge(self, fuel_text: str | None) -> QLabel:
        text = fuel_text or "UNKNOWN"
        badge = QLabel(text)
        badge.setMinimumHeight(20)
        badge.setContentsMargins(6, 1, 6, 1)

        styles = {
            "ULSFO": (
                "background-color:#0d718d; color:#ffffff; "
                "border:1px solid #1aa0b8; border-radius:4px; font-weight:700;"
            ),
            "VLSFO": (
                "background-color:#735511; color:#fff0bf; "
                "border:1px solid #b78a28; border-radius:4px; font-weight:700;"
            ),
            "MDO": (
                "background-color:#71332d; color:#ffe0da; "
                "border:1px solid #a95349; border-radius:4px; font-weight:700;"
            ),
        }

        badge.setStyleSheet(
            styles.get(
                text,
                "background-color:#233845; color:#a8c1cf; "
                "border:1px solid #3b5666; border-radius:4px; font-weight:700;",
            )
        )
        return badge

    def _fuel_display_for_stage(
        self,
        stage: OperationalStage,
        machinery: str,
    ) -> str | None:
        if self._active_fuel_state is None:
            return None

        fuel = self._active_fuel_state.fuel_for(machinery)
        at_utc = _as_naive_utc(stage.start_utc)

        if at_utc is not None:
            for event in sorted(
                self._fuel_changeovers,
                key=lambda item: _as_naive_utc(item.effective_at_utc) or datetime.min,
            ):
                event_at = _as_naive_utc(event.effective_at_utc)
                if (
                    event.machinery == machinery
                    and event_at is not None
                    and event_at <= at_utc
                ):
                    fuel = event.to_fuel_type

        stage_changes = [
            event
            for event in stage.changeovers
            if event.machinery == machinery
        ]

        if stage_changes:
            chain = [fuel]
            for event in sorted(
                stage_changes,
                key=lambda item: _as_naive_utc(item.effective_at_utc) or datetime.min,
            ):
                if event.to_fuel_type != chain[-1]:
                    chain.append(event.to_fuel_type)
            return "->".join(chain)

        return fuel

    def _machinery_totals(
        self,
        stage: OperationalStage,
    ) -> dict[str, float | None]:
        unknown = {
            "MAIN_ENGINE": None,
            "GENERATORS": None,
            "AUX_BOILER": None,
        }

        if stage.stage_type == STAGE_PORT_STAY:
            if stage.port_breakdown is None:
                return unknown
            return {
                "MAIN_ENGINE": 0.0,
                "GENERATORS": self._fuel_allocation_total(
                    stage.port_breakdown.generator_consumed_mt
                ),
                "AUX_BOILER": self._fuel_allocation_total(
                    stage.port_breakdown.boiler_consumed_mt
                ),
            }

        if stage.stage_type == STAGE_SEA_PASSAGE:
            if stage.leg is None:
                return unknown

            generator = stage.leg.sea_generator_consumed_mt
            boiler = stage.leg.sea_boiler_consumed_mt

            if generator is None or boiler is None:
                return unknown

            main_engine = {
                fuel_type: _subtract_optional(
                    stage.consumption_mt.get(fuel_type),
                    generator.get(fuel_type),
                    boiler.get(fuel_type),
                )
                for fuel_type in FUEL_TYPES
            }

            return {
                "MAIN_ENGINE": self._fuel_allocation_total(main_engine),
                "GENERATORS": self._fuel_allocation_total(generator),
                "AUX_BOILER": self._fuel_allocation_total(boiler),
            }

        duration = _hours(stage.start_utc, stage.end_utc)
        config = self._energy_config

        if duration is None or config is None:
            return unknown

        rates = {
            "MAIN_ENGINE": config.maneuvering_main_engine_mt_per_hour,
            "GENERATORS": config.maneuvering_generators_mt_per_hour,
            "AUX_BOILER": config.maneuvering_aux_boiler_mt_per_hour,
        }

        return {
            machinery: (
                None
                if rate is None
                else max(0.0, duration) * float(rate)
            )
            for machinery, rate in rates.items()
        }

    @staticmethod
    def _fuel_allocation_total(
        values: dict[str, float | None] | None,
    ) -> float | None:
        if values is None:
            return None

        quantities = [values.get(fuel_type) for fuel_type in FUEL_TYPES]
        if any(value is None for value in quantities):
            return None

        return sum(float(value or 0.0) for value in quantities)

    def _time_group(self, stage: OperationalStage) -> QWidget:
        frame, grid = _flat_grid()
        frame.setMinimumHeight(46)
        if stage.stage_type == STAGE_PORT_STAY:
            _add_metric(grid, 0, 0, "Arrival Scheduled", _fmt_dt(stage.event.arrival_at if stage.event else None))
            _add_metric(grid, 0, 1, "Actual Arrival", _fmt_actual(stage.incoming_leg, "actual_berth_arrival"))
            _add_metric(grid, 0, 2, "Departure Scheduled", _fmt_dt(stage.event.departure_at if stage.event else None))
            _add_metric(grid, 0, 3, "Actual Departure", _fmt_actual(stage.leg, "actual_berth_departure"))
            _add_metric(grid, 0, 4, "Predicted Duration", _fmt_duration(_hours(stage.start_utc, stage.end_utc)))
        elif stage.stage_type == STAGE_DEPARTURE_MANEUVERING:
            _add_metric(grid, 0, 0, "Berth Departure", _fmt_dt(stage.start_utc))
            _add_metric(grid, 0, 1, "Pilot Off", _fmt_dt(stage.end_utc))
            _add_metric(grid, 0, 2, "Duration", _fmt_duration(_hours(stage.start_utc, stage.end_utc)))
            _add_metric(grid, 0, 3, "Basis", "UTC")
        elif stage.stage_type == STAGE_SEA_PASSAGE:
            _add_metric(grid, 0, 0, "Pilot Off", _fmt_dt(stage.start_utc))
            _add_metric(grid, 0, 1, "Pilot On Target", _fmt_dt(stage.end_utc))
            _add_metric(grid, 0, 2, "Sea Time", _fmt_duration(stage.leg.sea_hours if stage.leg else 0))
            _add_metric(grid, 0, 3, "Basis", "UTC")
        else:
            _add_metric(grid, 0, 0, "Pilot On", _fmt_dt(stage.start_utc))
            _add_metric(grid, 0, 1, "Berth Arrival", _fmt_dt(stage.end_utc))
            _add_metric(grid, 0, 2, "Duration", _fmt_duration(_hours(stage.start_utc, stage.end_utc)))
            _add_metric(grid, 0, 3, "Basis", "UTC")
        return frame

    def _operations_group(self, stage: OperationalStage) -> QWidget:
        frame, grid = _flat_grid()
        if stage.stage_type == STAGE_PORT_STAY:
            frame.setMinimumHeight(46)
            breakdown = stage.port_breakdown
            _add_metric(grid, 0, 0, "Arrival Reefers", _fmt_number(breakdown.reefers if breakdown else 0))
            _add_metric(grid, 0, 1, "Expected Dep. Reefers", _fmt_number(_override_value(stage.leg, "departure_reefers")))
            _add_metric(grid, 0, 2, "Actual Dep. Reefers", _fmt_optional_number(_override_value_or_none(stage.leg, "actual_departure_reefers")))
            _add_metric(grid, 0, 3, "Ambient", _fmt_c(_override_value_or_none(stage.leg, "port_ambient_c")))
            _add_metric(grid, 0, 4, "kW / Reefer", _fmt_kw(breakdown.reefer_kw_per_unit if breakdown else None))
            _add_metric(grid, 0, 5, "Electrical Load", _fmt_kw(breakdown.total_electrical_load_kw if breakdown else None))
            _add_metric(grid, 0, 6, "DG Load", _fmt_percent(breakdown.generator_load_percent if breakdown else None))
        elif stage.stage_type == STAGE_DEPARTURE_MANEUVERING:
            frame.setMinimumHeight(46)
            _add_metric(grid, 0, 0, "Pilot Distance", _fmt_nm(_route_value(stage.leg, "departure_pilot_distance_nm")))
            _add_metric(grid, 0, 1, "Pilot Duration", _fmt_duration(_hours(stage.start_utc, stage.end_utc)))
            _add_metric(grid, 0, 2, "Actual Departure", _fmt_actual(stage.leg, "actual_berth_departure"))
            _add_metric(grid, 0, 3, "Actual Pilot Off", _fmt_actual(stage.leg, "actual_pilot_off"))
        elif stage.stage_type == STAGE_SEA_PASSAGE:
            frame.setMinimumHeight(88)
            _add_metric(grid, 0, 0, "Sea Distance", _fmt_nm(stage.leg.sea_distance_nm if stage.leg else 0))
            _add_metric(grid, 0, 1, "Sea Time", _fmt_duration(stage.leg.sea_hours if stage.leg else None))
            _add_metric(grid, 0, 2, "Speed", _fmt_kn(stage.leg.required_speed_knots if stage.leg else None))
            _add_metric(grid, 0, 3, "RPM", _fmt_rpm(stage.leg.predicted_rpm if stage.leg else None))
            _add_metric(grid, 0, 4, "ME Power", _fmt_kw(stage.leg.predicted_me_power_kw if stage.leg else None))
            _add_metric(grid, 0, 5, "ME Load", _fmt_percent(stage.leg.predicted_me_load_percent if stage.leg else None))
            _add_metric(grid, 1, 0, "ME SFOC", _fmt_sfoc(stage.leg.predicted_me_sfoc_g_per_kwh if stage.leg else None))
            _add_metric(grid, 1, 1, "ME MT/h", _fmt_mtph(stage.leg.predicted_me_fuel_mt_per_hour if stage.leg else None))
            _add_metric(grid, 1, 2, "Reefers", _fmt_number(_effective_reefers_for_display(stage.leg)))
            _add_metric(grid, 1, 3, "Ambient", _fmt_c(_override_value_or_none(stage.leg, "sea_ambient_c")))
            _add_metric(grid, 1, 4, "DG Load", _fmt_percent(stage.leg.sea_generator_load_percent if stage.leg else None))
            _add_metric(grid, 1, 5, "EGB", _egb_label(stage.leg))
        else:
            frame.setMinimumHeight(46)
            _add_metric(grid, 0, 0, "Pilot Distance", _fmt_nm(_route_value(stage.leg, "arrival_pilot_distance_nm")))
            _add_metric(grid, 0, 1, "Pilot Duration", _fmt_duration(_hours(stage.start_utc, stage.end_utc)))
            _add_metric(grid, 0, 2, "Actual Pilot On", _fmt_actual(stage.leg, "actual_pilot_on"))
            _add_metric(grid, 0, 3, "Actual Arrival", _fmt_actual(stage.leg, "actual_berth_arrival"))
        return frame

    def _consumption_group(self, stage: OperationalStage) -> QWidget:
        frame, grid = _flat_grid()
        frame.setMinimumHeight(130)
        _add_consumption_header(grid)
        if stage.stage_type == STAGE_PORT_STAY and stage.port_breakdown is not None:
            _add_consumption_row(grid, 1, "Generators", stage.port_breakdown.generator_consumed_mt)
            _add_consumption_row(grid, 2, "Aux Boiler", stage.port_breakdown.boiler_consumed_mt)
            _add_consumption_row(grid, 3, "TOTAL", stage.consumption_mt)
            _add_metric(grid, 4, 0, "Calculation", stage.port_breakdown.calculation_mode)
        elif stage.stage_type == STAGE_SEA_PASSAGE and stage.leg is not None:
            generator = stage.leg.sea_generator_consumed_mt or {fuel: 0.0 for fuel in FUEL_TYPES}
            boiler = stage.leg.sea_boiler_consumed_mt or {fuel: 0.0 for fuel in FUEL_TYPES}
            main_engine = {
                fuel: _subtract_optional(stage.consumption_mt[fuel], generator.get(fuel, 0.0), boiler.get(fuel, 0.0))
                for fuel in FUEL_TYPES
            }
            _add_consumption_row(grid, 1, "Main Engine", main_engine)
            _add_consumption_row(grid, 2, "Generators", generator)
            _add_consumption_row(grid, 3, "Aux Boiler", boiler)
            _add_consumption_row(grid, 4, "TOTAL", stage.consumption_mt)
            _add_metric(grid, 5, 0, "Calculation", stage.leg.sea_calculation_mode)
        else:
            _add_consumption_row(grid, 1, "Stage", stage.consumption_mt)
            _add_consumption_row(grid, 2, "TOTAL", stage.consumption_mt)
            _add_metric(grid, 3, 0, "Calculation", "DETAILED SFOC" if stage.total_consumption_mt is not None else "INCOMPLETE")
        return frame

    def _rob_group(self, stage: OperationalStage) -> QWidget:
        frame, grid = _flat_grid()
        frame.setMinimumHeight(84)
        grid.addWidget(QLabel("Fuel"), 1, 0)
        grid.addWidget(QLabel("START"), 1, 1)
        grid.addWidget(QLabel("CONSUMED"), 1, 2)
        grid.addWidget(QLabel("END"), 1, 3)
        for row, fuel_type in enumerate(FUEL_TYPES, start=2):
            _add_plain(grid, row, 0, fuel_type)
            _add_plain(grid, row, 1, _fmt_mt(stage.rob.start_mt[fuel_type]))
            _add_plain(grid, row, 2, _fmt_mt(stage.consumption_mt.get(fuel_type, 0.0)))
            _add_plain(grid, row, 3, _fmt_mt(stage.rob.end_mt[fuel_type]))
        return frame

    def _changeover_group(self, stage: OperationalStage) -> QWidget | None:
        frame = QWidget()
        frame.setMinimumHeight(44)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        summary = QLabel(_changeover_summary(stage.changeovers))
        summary.setObjectName("mutedText")
        summary.setWordWrap(True)
        checkbox = QCheckBox("Fuel Changeover Required")
        editor = QWidget()
        editor_layout = QGridLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        machinery = QComboBox()
        machinery.addItems(MACHINERY_TYPES)
        current_fuel = QLabel(_active_fuel_label(self._active_fuel_state, tuple(self._voyage_service.list_fuel_changeovers(self._vessel_service.get_active_vessel().id)) if self._vessel_service.get_active_vessel() else (), stage.start_utc, machinery.currentText()))
        current_fuel.setObjectName("mutedText")
        change_to = QComboBox()
        change_to.addItems(FUEL_TYPES)
        planned = QDateTimeEdit()
        planned.setCalendarPopup(True)
        planned.setDisplayFormat("dd MMM yyyy HH:mm")
        planned.setDateTime(QDateTime(stage.start_utc or datetime.now()))
        actual_enabled = QCheckBox("Actual changeover completed")
        actual = QDateTimeEdit()
        actual.setCalendarPopup(True)
        actual.setDisplayFormat("dd MMM yyyy HH:mm")
        actual.setDateTime(QDateTime(stage.start_utc or datetime.now()))
        actual.setEnabled(False)
        actual_enabled.toggled.connect(actual.setEnabled)
        machinery.currentTextChanged.connect(lambda value: current_fuel.setText(_active_fuel_label(self._active_fuel_state, tuple(self._voyage_service.list_fuel_changeovers(self._vessel_service.get_active_vessel().id)) if self._vessel_service.get_active_vessel() else (), stage.start_utc, value)))
        add_button = QPushButton("Add Changeover")
        add_button.setObjectName("primaryButton")
        add_button.clicked.connect(lambda checked=False: self._add_changeover(stage, machinery.currentText(), current_fuel.text(), change_to.currentText(), planned.dateTime().toPython(), actual.dateTime().toPython() if actual_enabled.isChecked() else None))
        editor_layout.addWidget(QLabel("Machinery"), 0, 0)
        editor_layout.addWidget(machinery, 0, 1)
        editor_layout.addWidget(QLabel("Current Fuel"), 0, 2)
        editor_layout.addWidget(current_fuel, 0, 3)
        editor_layout.addWidget(QLabel("Change To"), 1, 0)
        editor_layout.addWidget(change_to, 1, 1)
        editor_layout.addWidget(QLabel("Planned Changeover UTC"), 1, 2)
        editor_layout.addWidget(planned, 1, 3)
        editor_layout.addWidget(actual_enabled, 2, 0)
        editor_layout.addWidget(actual, 2, 1)
        editor_layout.addWidget(add_button, 2, 3)
        editor.setVisible(False)
        checkbox.toggled.connect(editor.setVisible)
        layout.addWidget(summary)
        layout.addWidget(checkbox)
        layout.addWidget(editor)
        return frame

    def _edit_stage(self, stage: OperationalStage) -> None:
        dialog = StageEditDialog(stage, self._latest_observation_for(stage), self)
        dialog.actual_rob_requested.connect(
            lambda selected=stage, details=dialog: self._update_actual_rob_from_details(details, selected)
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.actual_rob_updated:
            return
        values = dialog.values()
        self._save_stage_values(stage, values)

    def _save_stage_values(self, stage: OperationalStage, values: dict[str, object]) -> None:
        try:
            if stage.stage_type == STAGE_PORT_STAY:
                if stage.incoming_leg is not None and "actual_berth_arrival" in values:
                    self._save_leg_values(stage.incoming_leg, actual_berth_arrival=values["actual_berth_arrival"])
                if stage.leg is not None:
                    outgoing_values = {
                        key: values[key]
                        for key in ("actual_berth_departure", "port_reefers", "departure_reefers", "actual_departure_reefers", "port_ambient_c", "sea_ambient_c")
                        if key in values
                    }
                    self._save_leg_values(stage.leg, **outgoing_values)
            elif stage.leg is not None:
                self._save_leg_values(stage.leg, **values)
        except Exception as exc:
            QMessageBox.warning(self, "Stage values not saved", str(exc))
            return
        self.refresh()
        self.status_label.setText("Voyage stage saved and downstream table refreshed.")

    def _update_actual_rob_from_details(self, details: QDialog, stage: OperationalStage) -> None:
        if self._update_actual_rob(stage):
            if isinstance(details, StageEditDialog):
                details.actual_rob_updated = True
            details.accept()

    def _update_actual_rob(self, stage: OperationalStage) -> bool:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            return False
        dialog = ActualROBDialog(stage.rob.start_mt, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        values = dialog.values()
        try:
            self._voyage_service.save_actual_rob_observation(
                ActualROBObservation(
                    id=None,
                    vessel_id=vessel.id,
                    effective_at_utc=values["effective_at_utc"],
                    quantities_mt={
                        "ULSFO": values["ULSFO"],
                        "VLSFO": values["VLSFO"],
                        "MDO": values["MDO"],
                    },
                    remarks=values["remarks"],
                )
            )
        except Exception as exc:
            QMessageBox.warning(self, "Actual ROB not saved", str(exc))
            return False
        self.refresh()
        self.status_label.setText("Actual ROB observation saved; future rows refreshed from the new anchor.")
        return True

    def _save_leg_values(self, row: CalculatedVoyageLeg, **updates) -> None:
        override = row.leg.override
        self._voyage_service.save_leg_values(
            row.leg,
            departure_pilot_distance_nm=updates.get("departure_pilot_distance_nm", _effective(override.departure_pilot_distance_nm if override else None, row.leg.route.departure_pilot_distance_nm)),
            departure_pilotage_hours=updates.get("departure_pilotage_hours", _effective(override.departure_pilotage_hours if override else None, row.leg.route.departure_pilotage_hours)),
            sea_distance_nm=updates.get("sea_distance_nm", _effective(override.sea_distance_nm if override else None, row.leg.route.sea_distance_nm)),
            arrival_pilot_distance_nm=updates.get("arrival_pilot_distance_nm", _effective(override.arrival_pilot_distance_nm if override else None, row.leg.route.arrival_pilot_distance_nm)),
            arrival_pilotage_hours=updates.get("arrival_pilotage_hours", _effective(override.arrival_pilotage_hours if override else None, row.leg.route.arrival_pilotage_hours)),
            actual_berth_departure=updates.get("actual_berth_departure", override.actual_berth_departure if override else None),
            actual_pilot_off=updates.get("actual_pilot_off", override.actual_pilot_off if override else None),
            actual_pilot_on=updates.get("actual_pilot_on", override.actual_pilot_on if override else None),
            actual_berth_arrival=updates.get("actual_berth_arrival", override.actual_berth_arrival if override else None),
            port_reefers=updates.get("port_reefers", override.port_reefers if override else 0.0),
            departure_reefers=updates.get("departure_reefers", override.departure_reefers if override else 0.0),
            actual_departure_reefers=updates.get("actual_departure_reefers", override.actual_departure_reefers if override else None),
            port_ambient_c=updates.get("port_ambient_c", override.port_ambient_c if override else None),
            sea_ambient_c=updates.get("sea_ambient_c", override.sea_ambient_c if override else None),
            use_egb=updates.get("use_egb", override.use_egb if override else False),
            save_library=False,
        )

    def _add_changeover(self, stage: OperationalStage, machinery: str, current_fuel: str, change_to: str, planned_at_utc: datetime, actual_at_utc: datetime | None) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            return
        try:
            self._voyage_service.save_fuel_changeover(
                FuelChangeoverEvent(
                    id=None,
                    vessel_id=vessel.id,
                    machinery=machinery,
                    from_fuel_type=current_fuel if current_fuel in FUEL_TYPES else FUEL_TYPES[0],
                    to_fuel_type=change_to,
                    planned_at_utc=planned_at_utc,
                    actual_at_utc=actual_at_utc,
                    time_basis="UTC",
                    status="PLANNED",
                )
            )
        except Exception as exc:
            QMessageBox.warning(self, "Changeover not saved", str(exc))
            return
        self.refresh()
        self.status_label.setText(f"Fuel changeover added for {stage.title}; downstream projections refreshed.")


class NewChangeoverDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Operational Event — Fuel Changeover")
        self._controls: dict[str, tuple[QCheckBox, QComboBox, QComboBox]] = {}
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        layout.addLayout(grid)
        self.planned = QDateTimeEdit(QDateTime.currentDateTimeUtc())
        self.planned.setCalendarPopup(True)
        self.planned.setDisplayFormat("dd MMM yyyy HH:mm")
        grid.addWidget(QLabel("Planned UTC"), 0, 0)
        grid.addWidget(self.planned, 0, 1, 1, 2)
        for row, (machinery, label) in enumerate((("MAIN_ENGINE", "Main Engine"), ("GENERATORS", "Auxiliary Engines"), ("AUX_BOILER", "Auxiliary Boiler")), start=1):
            enabled = QCheckBox(label)
            from_fuel = QComboBox()
            from_fuel.addItem("Select from fuel")
            from_fuel.addItems(FUEL_TYPES)
            to_fuel = QComboBox()
            to_fuel.addItems(FUEL_TYPES)
            from_fuel.setEnabled(False)
            to_fuel.setEnabled(False)
            enabled.toggled.connect(from_fuel.setEnabled)
            enabled.toggled.connect(to_fuel.setEnabled)
            grid.addWidget(enabled, row, 0)
            grid.addWidget(from_fuel, row, 1)
            grid.addWidget(to_fuel, row, 2)
            self._controls[machinery] = (enabled, from_fuel, to_fuel)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        selected = [controls for controls in self._controls.values() if controls[0].isChecked()]
        if not selected:
            QMessageBox.warning(self, "Fuel Changeover", "Select at least one machinery item.")
            return
        if any(from_fuel.currentIndex() == 0 for _, from_fuel, _ in selected):
            QMessageBox.warning(self, "Fuel Changeover", "Select the current fuel for each changed machinery item.")
            return
        self.accept()

    def events(self, vessel_id: int) -> tuple[FuelChangeoverEvent, ...]:
        return tuple(
            FuelChangeoverEvent(
                id=None,
                vessel_id=vessel_id,
                machinery=machinery,
                from_fuel_type=from_fuel.currentText(),
                to_fuel_type=to_fuel.currentText(),
                planned_at_utc=self.planned.dateTime().toPython(),
                actual_at_utc=None,
                time_basis="UTC",
                status="PLANNED",
            )
            for machinery, (enabled, from_fuel, to_fuel) in self._controls.items()
            if enabled.isChecked()
        )


class ChangeoverDetailsDialog(QDialog):
    def __init__(self, changeovers: tuple[FuelChangeoverEvent, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Fuel Changeover Details")
        self._changeovers = changeovers
        self.delete_requested = False
        self._controls: dict[str, tuple[QComboBox, QComboBox]] = {}
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        layout.addLayout(grid)
        first = changeovers[0]
        self.planned = QDateTimeEdit(QDateTime(first.planned_at_utc))
        self.planned.setCalendarPopup(True)
        self.planned.setDisplayFormat("dd MMM yyyy HH:mm")
        self.actual_enabled = QCheckBox("Actual time entered")
        self.actual_enabled.setChecked(all(event.actual_at_utc is not None for event in changeovers))
        self.actual = QDateTimeEdit(QDateTime(first.actual_at_utc or first.planned_at_utc))
        self.actual.setCalendarPopup(True)
        self.actual.setDisplayFormat("dd MMM yyyy HH:mm")
        self.actual.setEnabled(self.actual_enabled.isChecked())
        self.actual_enabled.toggled.connect(self.actual.setEnabled)
        grid.addWidget(QLabel("Planned UTC"), 0, 0)
        grid.addWidget(self.planned, 0, 1)
        grid.addWidget(self.actual_enabled, 1, 0)
        grid.addWidget(self.actual, 1, 1)
        for row, event in enumerate(changeovers, start=2):
            label = {"MAIN_ENGINE": "Main Engine", "GENERATORS": "Auxiliary Engines", "AUX_BOILER": "Auxiliary Boiler"}[event.machinery]
            from_fuel = QComboBox()
            to_fuel = QComboBox()
            from_fuel.addItems(FUEL_TYPES)
            to_fuel.addItems(FUEL_TYPES)
            from_fuel.setCurrentText(event.from_fuel_type)
            to_fuel.setCurrentText(event.to_fuel_type)
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(from_fuel, row, 1)
            grid.addWidget(to_fuel, row, 2)
            self._controls[event.machinery] = (from_fuel, to_fuel)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        delete = QPushButton("Delete Changeover")
        delete.setObjectName("dangerButton")
        delete.clicked.connect(self._request_delete)
        buttons.addButton(delete, QDialogButtonBox.ButtonRole.DestructiveRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _request_delete(self) -> None:
        if QMessageBox.question(self, "Delete fuel changeover", "Delete the selected fuel changeover event(s)?") == QMessageBox.StandardButton.Yes:
            self.delete_requested = True
            self.accept()

    def events(self, vessel_id: int) -> tuple[FuelChangeoverEvent, ...]:
        actual = self.actual.dateTime().toPython() if self.actual_enabled.isChecked() else None
        return tuple(
            FuelChangeoverEvent(
                id=event.id,
                vessel_id=vessel_id,
                machinery=event.machinery,
                from_fuel_type=self._controls[event.machinery][0].currentText(),
                to_fuel_type=self._controls[event.machinery][1].currentText(),
                planned_at_utc=self.planned.dateTime().toPython(),
                actual_at_utc=actual,
                time_basis=event.time_basis,
                status="ACTUAL" if actual is not None else "PLANNED",
            )
            for event in self._changeovers
        )


class StageEditDialog(QDialog):
    actual_rob_requested = Signal()

    def __init__(
        self,
        stage: OperationalStage,
        latest_observation: ActualROBObservation | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Event Details — {stage.title}")
        self._stage = stage
        self._actual_controls: dict[str, tuple[QCheckBox, QDateTimeEdit]] = {}
        self._spin_controls: dict[str, QDoubleSpinBox] = {}
        self._egb_control: QCheckBox | None = None
        self.actual_rob_updated = False

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        event_tab = QWidget()
        event_layout = QVBoxLayout(event_tab)
        form = QGridLayout()
        event_layout.addLayout(form)
        event_layout.addStretch()
        tabs.addTab(event_tab, "Event")
        form.addWidget(QLabel("Event"), 0, 0)
        form.addWidget(QLabel(stage.title), 0, 1)
        form.addWidget(QLabel("Start UTC"), 1, 0)
        form.addWidget(QLabel(_fmt_dt(stage.start_utc)), 1, 1)
        form.addWidget(QLabel("End UTC"), 2, 0)
        form.addWidget(QLabel(_fmt_dt(stage.end_utc)), 2, 1)
        form.addWidget(QLabel("Duration"), 3, 0)
        form.addWidget(QLabel(_fmt_duration(_hours(stage.start_utc, stage.end_utc))), 3, 1)
        row = 4
        if stage.stage_type == STAGE_PORT_STAY:
            if stage.incoming_leg is not None:
                row = self._add_actual(form, row, "Actual Arrival", "actual_berth_arrival", stage.incoming_leg.leg.override.actual_berth_arrival if stage.incoming_leg.leg.override else None, stage.start_utc)
            if stage.leg is not None:
                row = self._add_actual(form, row, "Actual Departure", "actual_berth_departure", stage.leg.leg.override.actual_berth_departure if stage.leg.leg.override else None, stage.end_utc)
                row = self._add_spin(form, row, "Arrival Reefers", "port_reefers", _override_value(stage.leg, "port_reefers"), "")
                row = self._add_spin(form, row, "Expected Departure Reefers", "departure_reefers", _override_value(stage.leg, "departure_reefers"), "")
                row = self._add_spin(form, row, "Actual Departure Reefers", "actual_departure_reefers", _override_value(stage.leg, "actual_departure_reefers"), "")
                row = self._add_spin(form, row, "Port Ambient Temp", "port_ambient_c", _override_value_or_default(stage.leg, "port_ambient_c", 20.0), " °C")
                row = self._add_spin(form, row, "Sea Ambient Temp", "sea_ambient_c", _override_value_or_default(stage.leg, "sea_ambient_c", 20.0), " °C")
        elif stage.stage_type == STAGE_DEPARTURE_MANEUVERING and stage.leg is not None:
            row = self._add_actual(form, row, "Actual Berth Departure", "actual_berth_departure", _actual(stage.leg, "actual_berth_departure"), stage.start_utc)
            row = self._add_spin(form, row, "Pilot Distance NM", "departure_pilot_distance_nm", _route_value(stage.leg, "departure_pilot_distance_nm"), " NM")
            row = self._add_spin(form, row, "Pilot Duration", "departure_pilotage_hours", stage.leg.departure_pilotage_hours, " h")
            row = self._add_actual(form, row, "Actual Pilot Off", "actual_pilot_off", _actual(stage.leg, "actual_pilot_off"), stage.end_utc)
        elif stage.stage_type == STAGE_SEA_PASSAGE and stage.leg is not None:
            row = self._add_actual(form, row, "Actual Pilot Off", "actual_pilot_off", _actual(stage.leg, "actual_pilot_off"), stage.start_utc)
            row = self._add_spin(form, row, "Sea Distance NM", "sea_distance_nm", stage.leg.sea_distance_nm, " NM")
            row = self._add_spin(form, row, "Departure Reefers", "departure_reefers", _override_value(stage.leg, "departure_reefers"), "")
            row = self._add_spin(form, row, "Actual Departure Reefers", "actual_departure_reefers", _override_value(stage.leg, "actual_departure_reefers"), "")
            row = self._add_spin(form, row, "Sea Ambient Temp", "sea_ambient_c", _override_value_or_default(stage.leg, "sea_ambient_c", 20.0), " °C")
            self._egb_control = QCheckBox("Use EGB when available")
            self._egb_control.setChecked(stage.leg.egb_used)
            self._egb_control.setEnabled(stage.leg.egb_available)
            form.addWidget(self._egb_control, row, 0, 1, 2)
            row += 1
            row = self._add_actual(form, row, "Actual Pilot On", "actual_pilot_on", _actual(stage.leg, "actual_pilot_on"), stage.end_utc)
        elif stage.stage_type == STAGE_ARRIVAL_MANEUVERING and stage.leg is not None:
            row = self._add_actual(form, row, "Actual Pilot On", "actual_pilot_on", _actual(stage.leg, "actual_pilot_on"), stage.start_utc)
            row = self._add_spin(form, row, "Pilot Distance NM", "arrival_pilot_distance_nm", _route_value(stage.leg, "arrival_pilot_distance_nm"), " NM")
            row = self._add_spin(form, row, "Pilot Duration", "arrival_pilotage_hours", stage.leg.arrival_pilotage_hours, " h")
            row = self._add_actual(form, row, "Actual Berth Arrival", "actual_berth_arrival", _actual(stage.leg, "actual_berth_arrival"), stage.end_utc)

        tabs.addTab(_detail_consumption_tab(stage), "Consumption")
        rob_tab = _detail_rob_tab(stage, latest_observation, self.actual_rob_requested.emit)
        tabs.addTab(rob_tab, "ROB")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[str, object]:
        values: dict[str, object] = {key: control.value() for key, control in self._spin_controls.items()}
        for key, (enabled, editor) in self._actual_controls.items():
            values[key] = editor.dateTime().toPython() if enabled.isChecked() else None
        if self._egb_control is not None:
            values["use_egb"] = self._egb_control.isChecked()
        return values

    def _add_actual(self, grid: QGridLayout, row: int, label: str, key: str, value: datetime | None, fallback: datetime | None) -> int:
        enabled = QCheckBox(label)
        editor = QDateTimeEdit()
        editor.setCalendarPopup(True)
        editor.setDisplayFormat("dd MMM yyyy HH:mm")
        editor.setDateTime(QDateTime(value or fallback or datetime.now()))
        enabled.setChecked(value is not None)
        editor.setEnabled(value is not None)
        enabled.toggled.connect(editor.setEnabled)
        grid.addWidget(enabled, row, 0)
        grid.addWidget(editor, row, 1)
        self._actual_controls[key] = (enabled, editor)
        return row + 1

    def _add_spin(self, grid: QGridLayout, row: int, label: str, key: str, value: float, suffix: str) -> int:
        control = _spinbox(suffix, 0, 999999, 1 if suffix != " h" else 0.25)
        control.setValue(value)
        grid.addWidget(QLabel(label), row, 0)
        grid.addWidget(control, row, 1)
        self._spin_controls[key] = control
        return row + 1


def _flat_grid() -> tuple[QWidget, QGridLayout]:
    frame = QWidget()
    grid = QGridLayout(frame)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(8)
    return frame, grid


def _detail_consumption_tab(stage: OperationalStage) -> QWidget:
    tab = QWidget()
    layout = QVBoxLayout(tab)
    grid = QGridLayout()
    layout.addLayout(grid)
    for column, label in enumerate(("Machinery", *FUEL_TYPES, "Total")):
        grid.addWidget(QLabel(label), 0, column)
    for row, (source, values) in enumerate(_consumption_rows(stage), start=1):
        grid.addWidget(QLabel(source), row, 0)
        for column, fuel_type in enumerate(FUEL_TYPES, start=1):
            grid.addWidget(QLabel(_fmt_mt(values.get(fuel_type))), row, column)
        total = None if any(values.get(fuel) is None for fuel in FUEL_TYPES) else sum(
            float(values.get(fuel) or 0.0) for fuel in FUEL_TYPES
        )
        grid.addWidget(QLabel(_fmt_mt(total)), row, 4)
    if stage.changeovers:
        changeovers = QLabel(_changeover_summary(stage.changeovers))
        changeovers.setObjectName("mutedText")
        changeovers.setWordWrap(True)
        layout.addWidget(changeovers)
    layout.addStretch()
    return tab


def _consumption_rows(stage: OperationalStage) -> tuple[tuple[str, dict[str, float | None]], ...]:
    unavailable = {fuel: None for fuel in FUEL_TYPES}
    if stage.stage_type == STAGE_PORT_STAY and stage.port_breakdown is not None:
        return (
            ("Main Engine", unavailable),
            ("Auxiliary Engines", stage.port_breakdown.generator_consumed_mt),
            ("Auxiliary Boiler", stage.port_breakdown.boiler_consumed_mt),
            ("Total", stage.consumption_mt),
        )
    if stage.stage_type == STAGE_SEA_PASSAGE and stage.leg is not None:
        generators = stage.leg.sea_generator_consumed_mt
        boiler = stage.leg.sea_boiler_consumed_mt
        main_engine = unavailable if generators is None or boiler is None else {
            fuel: _subtract_optional(stage.consumption_mt.get(fuel), generators.get(fuel), boiler.get(fuel))
            for fuel in FUEL_TYPES
        }
        return (
            ("Main Engine", main_engine),
            ("Auxiliary Engines", generators or unavailable),
            ("Auxiliary Boiler", boiler or unavailable),
            ("Total", stage.consumption_mt),
        )
    return (("Stage consumption", stage.consumption_mt),)


def _detail_rob_tab(
    stage: OperationalStage,
    latest_observation: ActualROBObservation | None,
    on_update: object,
) -> QWidget:
    tab = QWidget()
    layout = QVBoxLayout(tab)
    grid = QGridLayout()
    layout.addLayout(grid)
    for column, label in enumerate(("Fuel", "Start", "Consumed", "End")):
        grid.addWidget(QLabel(label), 0, column)
    for row, fuel_type in enumerate(FUEL_TYPES, start=1):
        grid.addWidget(QLabel(fuel_type), row, 0)
        grid.addWidget(QLabel(_fmt_mt(stage.rob.start_mt.get(fuel_type))), row, 1)
        grid.addWidget(QLabel(_fmt_mt(stage.consumption_mt.get(fuel_type))), row, 2)
        grid.addWidget(QLabel(_fmt_mt(stage.rob.end_mt.get(fuel_type))), row, 3)
    if latest_observation is None:
        latest = QLabel("Latest relevant Actual ROB: none")
    else:
        quantities = _fmt_compact_rob(latest_observation.quantities_mt)
        remarks = f" — {latest_observation.remarks}" if latest_observation.remarks else ""
        latest = QLabel(
            f"Latest relevant Actual ROB: {_fmt_dt(latest_observation.effective_at_utc)} UTC | {quantities}{remarks}"
        )
    latest.setObjectName("mutedText")
    latest.setWordWrap(True)
    layout.addWidget(latest)
    update = QPushButton("Update Actual ROB")
    update.setObjectName("primaryButton")
    update.clicked.connect(on_update)
    layout.addWidget(update)
    layout.addStretch()
    return tab


def _flat_section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("fieldLabel")
    label.setMinimumHeight(18)
    return label


def _add_metric(grid: QGridLayout, row: int, column: int, label_text: str, value_text: str) -> None:
    label = QLabel(label_text)
    label.setObjectName("fieldLabel")
    label.setMinimumHeight(18)
    value = QLabel(value_text)
    value.setObjectName("mutedText")
    value.setMinimumHeight(18)
    value.setWordWrap(False)
    grid.addWidget(label, row * 2, column)
    grid.addWidget(value, row * 2 + 1, column)


def _add_consumption_header(grid: QGridLayout) -> None:
    for column, text in enumerate(("Source", "ULSFO", "VLSFO", "MDO", "Total")):
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        label.setMinimumHeight(18)
        grid.addWidget(label, 0, column)


def _add_consumption_row(grid: QGridLayout, row: int, source: str, values: dict[str, float | None]) -> None:
    _add_plain(grid, row, 0, source)
    for column, fuel_type in enumerate(FUEL_TYPES, start=1):
        _add_plain(grid, row, column, _fmt_mt(values.get(fuel_type, 0.0)))
    total_values = [values.get(fuel_type, 0.0) for fuel_type in FUEL_TYPES]
    total = None if any(value is None for value in total_values) else sum(float(value or 0.0) for value in total_values)
    _add_plain(grid, row, 4, _fmt_mt(total))


def _add_plain(grid: QGridLayout, row: int, column: int, text: str) -> None:
    label = QLabel(text)
    label.setObjectName("mutedText")
    label.setMinimumHeight(18)
    grid.addWidget(label, row, column)


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def _spinbox(suffix: str, minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
    spinbox = QDoubleSpinBox()
    spinbox.setDecimals(2)
    spinbox.setRange(minimum, maximum)
    spinbox.setSingleStep(step)
    spinbox.setSuffix(suffix)
    return spinbox


def _fmt_dt(value: datetime | None) -> str:
    return value.strftime("%d %b %Y %H:%M") if value else "-"


def _fmt_actual(leg: CalculatedVoyageLeg | None, key: str) -> str:
    value = _actual(leg, key)
    return _fmt_dt(value) if value else "--"


def _actual(leg: CalculatedVoyageLeg | None, key: str) -> datetime | None:
    if leg is None or leg.leg.override is None:
        return None
    return getattr(leg.leg.override, key)


def _fmt_duration(hours: float | None) -> str:
    if hours is None:
        return "-"
    total_minutes = round(max(0.0, hours) * 60)
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


def _hours(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return max(0.0, (end - start).total_seconds() / 3600)


def _fmt_fuel_line(values: dict[str, float | None]) -> str:
    return "  |  ".join(f"{fuel} {_fmt_mt(values.get(fuel, 0.0))}" for fuel in FUEL_TYPES)


def _fmt_compact_rob(values: dict[str, float | None]) -> str:
    labels = {"ULSFO": "U", "VLSFO": "V", "MDO": "M"}
    return " | ".join(
        f"{labels[fuel]} {_fmt_compact_mt(values.get(fuel))}"
        for fuel in FUEL_TYPES
    )


def _fmt_compact_mt(value: float | None) -> str:
    return "-" if value is None else f"{float(value):.2f}"


def _fmt_observation(observation: ActualROBObservation | None) -> str:
    return _fmt_dt(observation.effective_at_utc) if observation is not None else "-"


def _stage_label(stage: OperationalStage) -> str:
    return {
        STAGE_PORT_STAY: "Port stay",
        STAGE_DEPARTURE_MANEUVERING: "Departure maneuvering",
        STAGE_SEA_PASSAGE: "Sea passage",
        STAGE_ARRIVAL_MANEUVERING: "Arrival maneuvering",
    }.get(stage.stage_type, stage.stage_type)


def _stage_distance(stage: OperationalStage) -> str:
    if stage.stage_type == STAGE_SEA_PASSAGE:
        return _fmt_nm(stage.leg.sea_distance_nm if stage.leg else None)
    if stage.stage_type == STAGE_DEPARTURE_MANEUVERING:
        return _fmt_nm(_route_value(stage.leg, "departure_pilot_distance_nm"))
    if stage.stage_type == STAGE_ARRIVAL_MANEUVERING:
        return _fmt_nm(_route_value(stage.leg, "arrival_pilot_distance_nm"))
    return "-"


def _stage_dg_load(stage: OperationalStage) -> str:
    if stage.stage_type == STAGE_SEA_PASSAGE and stage.leg is not None:
        return _fmt_percent(stage.leg.sea_generator_load_percent)
    if stage.stage_type == STAGE_PORT_STAY and stage.port_breakdown is not None:
        return _fmt_percent(stage.port_breakdown.generator_load_percent)
    return "-"


def _stage_issue(stage: OperationalStage) -> str:
    if (
        stage.stage_type == STAGE_SEA_PASSAGE
        and (stage.leg is None or stage.leg.sea_distance_nm is None or stage.leg.sea_distance_nm <= 0)
    ):
        return "Missing sea distance"
    if stage.total_consumption_mt is None:
        return "Consumption incomplete"
    if any(value is None for value in stage.rob.end_mt.values()):
        return "Predicted ROB unavailable"
    if stage.changeovers:
        return "Fuel changeover scheduled"
    return ""


def _fmt_mt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f} MT"


def _fmt_nm(value: float | None) -> str:
    return f"{value:.1f} NM" if value is not None else "-"


def _fmt_kn(value: float | None) -> str:
    return f"{value:.2f} kn" if value is not None else "-"


def _fmt_percent(value: float | None) -> str:
    return f"{value:.1f} %" if value is not None else "-"


def _fmt_kw(value: float | None) -> str:
    return f"{value:.0f} kW" if value is not None else "-"


def _fmt_rpm(value: float | None) -> str:
    return f"{value:.1f} RPM" if value is not None else "-"


def _fmt_sfoc(value: float | None) -> str:
    return f"{value:.1f} g/kWh" if value is not None else "-"


def _fmt_mtph(value: float | None) -> str:
    return f"{value:.3f} MT/h" if value is not None else "-"


def _fmt_factor(value: float | None) -> str:
    return f"{value:.7f}" if value is not None else "-"


def _fmt_c(value: float | None) -> str:
    return f"{value:.1f} °C" if value is not None else "-"


def _fmt_number(value: float | None) -> str:
    return f"{value:.0f}" if value is not None else "0"


def _fmt_optional_number(value: float | None) -> str:
    return f"{value:.0f}" if value is not None else "-"


def _route_value(leg: CalculatedVoyageLeg | None, key: str) -> float:
    if leg is None:
        return 0.0
    override_value = getattr(leg.leg.override, key) if leg.leg.override else None
    return _effective(override_value, getattr(leg.leg.route, key))


def _override_value(leg: CalculatedVoyageLeg | None, key: str) -> float:
    if leg is None or leg.leg.override is None:
        return 0.0
    value = getattr(leg.leg.override, key)
    return 0.0 if value is None else float(value)


def _override_value_or_none(leg: CalculatedVoyageLeg | None, key: str) -> float | None:
    if leg is None or leg.leg.override is None:
        return None
    value = getattr(leg.leg.override, key)
    return None if value is None else float(value)


def _override_value_or_default(leg: CalculatedVoyageLeg | None, key: str, default: float) -> float:
    value = _override_value_or_none(leg, key)
    return default if value is None else value


def _effective_reefers_for_display(leg: CalculatedVoyageLeg | None) -> float:
    actual = _override_value_or_none(leg, "actual_departure_reefers")
    if actual is not None:
        return actual
    return _override_value(leg, "departure_reefers")


def _effective(value: float | None, default: float) -> float:
    return float(default if value is None else value)


def _subtract_optional(value: float | None, *subtract: float | None) -> float | None:
    if value is None or any(item is None for item in subtract):
        return None
    return value - sum(float(item or 0.0) for item in subtract)


def _egb_label(leg: CalculatedVoyageLeg | None) -> str:
    if leg is None:
        return "-"
    if not leg.egb_available:
        return "Unavailable (<25% ME load)"
    return "Available / Used" if leg.egb_used else "Available / Not used"


def _changeover_summary(changeovers: tuple[FuelChangeoverEvent, ...]) -> str:
    if not changeovers:
        return "Fuel Changeovers: none for this stage."
    lines = ["FUEL CHANGEOVERS"]
    for event in changeovers:
        machinery = {"MAIN_ENGINE": "ME", "GENERATORS": "DG", "AUX_BOILER": "Aux Boiler"}.get(event.machinery, event.machinery)
        actual = _fmt_dt(event.actual_at_utc) if event.actual_at_utc else "--"
        lines.append(f"{machinery}: {event.from_fuel_type} -> {event.to_fuel_type} | Planned UTC {_fmt_dt(event.planned_at_utc)} | Actual {actual}")
    return "\n".join(lines)


def _changeover_fuel_text(event: FuelChangeoverEvent | None) -> str:
    return f"{event.from_fuel_type} -> {event.to_fuel_type}" if event is not None else "-"


def _active_fuel_label(state: MachineryFuelState | None, changeovers: tuple[FuelChangeoverEvent, ...], at_utc: datetime | None, machinery: str) -> str:
    if state is None:
        return "VLSFO"
    fuel = state.fuel_for(machinery)
    if at_utc is None:
        return fuel
    compare_at = _as_naive_utc(at_utc)
    for event in sorted(changeovers, key=lambda item: _as_naive_utc(item.effective_at_utc) or datetime.min):
        event_at = _as_naive_utc(event.effective_at_utc)
        if event.machinery == machinery and event_at is not None and compare_at is not None and event_at <= compare_at:
            fuel = event.to_fuel_type
    return fuel


def _current_stage_text(timeline: VoyageStageTimeline) -> str:
    if timeline.current_stage is not None:
        return timeline.current_stage.title
    if timeline.stages and all(stage.status == "PLANNED" for stage in timeline.stages):
        return "PRE-VOYAGE"
    return "Not determined"


def _as_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value
