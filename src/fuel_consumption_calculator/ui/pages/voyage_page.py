from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QDateTime, Qt
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
    QMessageBox,
    QPushButton,
    QScrollArea,
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
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.services.voyage_service import VoyageService
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader


class VoyagePage(QWidget):
    def __init__(
        self,
        vessel_service: VesselService,
        schedule_service: ScheduleService,
        consumption_service: ConsumptionService,
        voyage_service: VoyageService,
        rob_service: ROBService,
    ) -> None:
        super().__init__()
        self._vessel_service = vessel_service
        self._schedule_service = schedule_service
        self._consumption_service = consumption_service
        self._voyage_service = voyage_service
        self._rob_service = rob_service
        self._timeline: VoyageStageTimeline | None = None
        self._active_fuel_state: MachineryFuelState | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)
        layout.addWidget(PageHeader("Voyage Planner", "Sequential operational stage cards for port, maneuvering, and sea passage."))

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

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.card_container = QWidget()
        self.card_layout = QVBoxLayout(self.card_container)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(14)
        self.scroll.setWidget(self.card_container)
        layout.addWidget(self.scroll, 1)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("mutedText")
        layout.addWidget(self.status_label)
        self.refresh()

    def refresh(self) -> None:
        self._clear_cards()
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self.vessel_label.setText("Vessel: Not configured")
            self.current_stage_label.setText("Current Stage: -")
            self.next_port_label.setText("Next Port: -")
            self.next_event_label.setText("Next Major Event: -")
            self.summary_rob_label.setText("Current Predicted ROB: ULSFO 0.0 MT  |  VLSFO 0.0 MT  |  MDO 0.0 MT")
            self.empty_state.setVisible(True)
            self.scroll.setVisible(False)
            self.status_label.setText("Configure a vessel before planning voyage stages.")
            return

        events = self._schedule_service.list_events(vessel.id)
        schedule_timeline = self._schedule_service.get_timeline(vessel.id)
        if schedule_timeline.issues:
            self.empty_state.setVisible(True)
            self.scroll.setVisible(False)
            self.status_label.setText(f"Schedule chronology warning: {schedule_timeline.issues[0].message}")
            return

        profile = self._consumption_service.load_profile(vessel.id)
        plan = self._voyage_service.calculate_plan(vessel.id, events, profile)
        self._voyage_service.calculate_consumption_for_plan(events=events, timeline=schedule_timeline, plan=plan, profile=profile)
        starting_rob = self._rob_service.load_starting_rob(vessel.id)
        observations = self._voyage_service.list_actual_rob_observations(vessel.id)
        self._timeline = build_voyage_stage_timeline(events, plan, starting_rob, rob_observations=observations)
        self._active_fuel_state = plan.initial_fuel_state

        self.vessel_label.setText(f"Vessel: {vessel.name}  |  IMO {vessel.imo}")
        current = self._timeline.current_stage
        self.current_stage_label.setText(f"Current Stage: {current.title if current else 'Not determined'}")
        self.next_port_label.setText(f"Next Port: {self._timeline.next_port or '-'}")
        next_major = next((stage for stage in self._timeline.stages if stage.status != "COMPLETED"), None)
        self.next_event_label.setText(f"Next Major Event: {next_major.title if next_major else '-'}")
        self.summary_rob_label.setText("Current Predicted ROB: " + _fmt_fuel_line(self._timeline.current_predicted_rob_mt))

        self.empty_state.setVisible(len(self._timeline.stages) == 0)
        self.scroll.setVisible(len(self._timeline.stages) > 0)
        for stage in self._timeline.stages:
            self.card_layout.addWidget(self._build_card(stage))
        self.card_layout.addStretch()
        self.status_label.setText(f"Loaded {len(self._timeline.stages)} operational voyage stages.")

    def _clear_cards(self) -> None:
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_card(self, stage: OperationalStage) -> QFrame:
        card = QFrame()
        card.setObjectName({"CURRENT": "voyageStageCurrent", "COMPLETED": "voyageStageCompleted"}.get(stage.status, "voyageStagePlanned"))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        badge = QLabel(stage.status)
        badge.setObjectName({"CURRENT": "stageBadgeCurrent", "COMPLETED": "stageBadgeCompleted"}.get(stage.status, "stageBadgePlanned"))
        title = QLabel(stage.title)
        title.setObjectName("sectionTitle")
        subtitle = QLabel(stage.subtitle)
        subtitle.setObjectName("mutedText")
        edit_button = QPushButton("Edit Stage Values")
        edit_button.clicked.connect(lambda checked=False, selected=stage: self._edit_stage(selected))
        edit_button.setEnabled(stage.leg is not None or stage.incoming_leg is not None)
        rob_button = QPushButton("Update Actual ROB")
        rob_button.clicked.connect(lambda checked=False, selected=stage: self._update_actual_rob(selected))
        header.addWidget(badge)
        header.addWidget(title)
        header.addWidget(subtitle, 1)
        header.addWidget(edit_button)
        header.addWidget(rob_button)
        layout.addLayout(header)

        groups = QGridLayout()
        groups.setHorizontalSpacing(12)
        groups.setVerticalSpacing(12)
        groups.addWidget(self._time_group(stage), 0, 0)
        groups.addWidget(self._operations_group(stage), 0, 1)
        groups.addWidget(self._consumption_group(stage), 1, 0)
        groups.addWidget(self._rob_group(stage), 1, 1)
        groups.setColumnStretch(0, 1)
        groups.setColumnStretch(1, 1)
        layout.addLayout(groups)
        layout.addWidget(self._changeover_group(stage))
        return card

    def _time_group(self, stage: OperationalStage) -> QFrame:
        frame, grid = _group("TIME")
        if stage.stage_type == STAGE_PORT_STAY:
            _add_field(grid, 1, 0, "Arrival Scheduled / Maersk Local", _fmt_dt(stage.event.arrival_at if stage.event else None))
            _add_field(grid, 1, 1, "Actual Arrival", _fmt_actual(stage.incoming_leg, "actual_berth_arrival"))
            _add_field(grid, 2, 0, "Departure Scheduled / Maersk Local", _fmt_dt(stage.event.departure_at if stage.event else None))
            _add_field(grid, 2, 1, "Actual Departure", _fmt_actual(stage.leg, "actual_berth_departure"))
            _add_field(grid, 3, 0, "Predicted Port Stay", _fmt_duration(_hours(stage.start_utc, stage.end_utc)))
            _add_field(grid, 3, 1, "Calculation Basis", "Authoritative UTC")
        elif stage.stage_type == STAGE_DEPARTURE_MANEUVERING:
            _add_field(grid, 1, 0, "Berth Departure", _fmt_dt(stage.start_utc))
            _add_field(grid, 1, 1, "Pilot Off", _fmt_dt(stage.end_utc))
            _add_field(grid, 2, 0, "Duration", _fmt_duration(stage.leg.departure_pilotage_hours if stage.leg else 0))
            _add_field(grid, 2, 1, "Display Basis", "UTC")
        elif stage.stage_type == STAGE_SEA_PASSAGE:
            _add_field(grid, 1, 0, "Pilot Off", _fmt_dt(stage.start_utc))
            _add_field(grid, 1, 1, "Pilot On Target", _fmt_dt(stage.end_utc))
            _add_field(grid, 2, 0, "Available Sea Time", _fmt_duration(stage.leg.sea_hours if stage.leg else 0))
            _add_field(grid, 2, 1, "Display Basis", "UTC")
        else:
            _add_field(grid, 1, 0, "Pilot On", _fmt_dt(stage.start_utc))
            _add_field(grid, 1, 1, "Berth Arrival", _fmt_dt(stage.end_utc))
            _add_field(grid, 2, 0, "Duration", _fmt_duration(stage.leg.arrival_pilotage_hours if stage.leg else 0))
            _add_field(grid, 2, 1, "Display Basis", "UTC")
        return frame

    def _operations_group(self, stage: OperationalStage) -> QFrame:
        frame, grid = _group("OPERATIONS")
        if stage.stage_type == STAGE_PORT_STAY:
            breakdown = stage.port_breakdown
            _add_field(grid, 1, 0, "Arrival Reefers", _fmt_number(breakdown.reefers if breakdown else 0))
            _add_field(grid, 1, 1, "Expected / Actual Departure Reefers", f"{_fmt_number(_override_value(stage.leg, 'departure_reefers'))} / {_fmt_number(_override_value(stage.leg, 'actual_departure_reefers'))}")
            _add_field(grid, 2, 0, "Electrical Load", _fmt_kw(breakdown.total_electrical_load_kw if breakdown else None))
            _add_field(grid, 2, 1, "Generator Load", _fmt_percent(breakdown.generator_load_percent if breakdown else None))
            _add_field(grid, 3, 0, "Port Ambient / Reefer", f"{_fmt_c(_override_value_or_none(stage.leg, 'port_ambient_c'))} / {_fmt_kw(breakdown.reefer_kw_per_unit if breakdown else None)} each")
        elif stage.stage_type == STAGE_DEPARTURE_MANEUVERING:
            _add_field(grid, 1, 0, "Pilot Distance", _fmt_nm(_route_value(stage.leg, "departure_pilot_distance_nm")))
            _add_field(grid, 1, 1, "Pilot Duration", _fmt_duration(stage.leg.departure_pilotage_hours if stage.leg else 0))
            _add_field(grid, 2, 0, "Actual Berth Departure", _fmt_actual(stage.leg, "actual_berth_departure"))
            _add_field(grid, 2, 1, "Actual Pilot Off", _fmt_actual(stage.leg, "actual_pilot_off"))
        elif stage.stage_type == STAGE_SEA_PASSAGE:
            _add_field(grid, 1, 0, "Sea Distance", _fmt_nm(stage.leg.sea_distance_nm if stage.leg else 0))
            _add_field(grid, 1, 1, "Required Avg Speed", _fmt_kn(stage.leg.required_speed_knots if stage.leg else None))
            _add_field(grid, 2, 0, "Predicted ME Load", _fmt_percent(stage.leg.predicted_me_load_percent if stage.leg else None))
            _add_field(grid, 2, 1, "RPM / Power", f"{_fmt_rpm(stage.leg.predicted_rpm if stage.leg else None)} / {_fmt_kw(stage.leg.predicted_me_power_kw if stage.leg else None)}")
            _add_field(grid, 3, 0, "ME SFOC / Fuel Rate", f"{_fmt_sfoc(stage.leg.predicted_me_sfoc_g_per_kwh if stage.leg else None)} / {_fmt_mtph(stage.leg.predicted_me_fuel_mt_per_hour if stage.leg else None)}")
            _add_field(grid, 3, 1, "Hull Coefficient", _fmt_factor(stage.leg.hull_coefficient if stage.leg else None))
            _add_field(grid, 4, 0, "Departure Reefers", f"{_fmt_number(_override_value(stage.leg, 'departure_reefers'))} exp / {_fmt_number(_override_value(stage.leg, 'actual_departure_reefers'))} actual")
            _add_field(grid, 4, 1, "Sea Ambient / Reefer", f"{_fmt_c(_override_value_or_none(stage.leg, 'sea_ambient_c'))} / {_fmt_kw(stage.leg.departure_reefer_kw_per_unit if stage.leg else None)} each")
            _add_field(grid, 5, 0, "Generator Load", _fmt_kw(stage.leg.sea_total_electrical_load_kw if stage.leg else None))
            _add_field(grid, 5, 1, "EGB", _egb_label(stage.leg))
        else:
            _add_field(grid, 1, 0, "Pilot Distance", _fmt_nm(_route_value(stage.leg, "arrival_pilot_distance_nm")))
            _add_field(grid, 1, 1, "Pilot Duration", _fmt_duration(stage.leg.arrival_pilotage_hours if stage.leg else 0))
            _add_field(grid, 2, 0, "Actual Pilot On", _fmt_actual(stage.leg, "actual_pilot_on"))
            _add_field(grid, 2, 1, "Actual Berth Arrival", _fmt_actual(stage.leg, "actual_berth_arrival"))
        return frame

    def _consumption_group(self, stage: OperationalStage) -> QFrame:
        frame, grid = _group("STAGE CONSUMPTION")
        if stage.stage_type == STAGE_PORT_STAY and stage.port_breakdown is not None:
            _add_field(grid, 1, 0, "Generators", _fmt_fuel_line(stage.port_breakdown.generator_consumed_mt))
            _add_field(grid, 2, 0, "Aux Boiler", _fmt_fuel_line(stage.port_breakdown.boiler_consumed_mt))
            _add_field(grid, 3, 0, "Total", _fmt_fuel_line(stage.consumption_mt))
        elif stage.stage_type == STAGE_SEA_PASSAGE and stage.leg is not None:
            generator = stage.leg.sea_generator_consumed_mt or {fuel: 0.0 for fuel in FUEL_TYPES}
            boiler = stage.leg.sea_boiler_consumed_mt or {fuel: 0.0 for fuel in FUEL_TYPES}
            main_engine = {fuel: stage.consumption_mt[fuel] - generator.get(fuel, 0.0) - boiler.get(fuel, 0.0) for fuel in FUEL_TYPES}
            _add_field(grid, 1, 0, "Main Engine", _fmt_fuel_line(main_engine))
            _add_field(grid, 2, 0, "Generators", _fmt_fuel_line(generator))
            _add_field(grid, 3, 0, "Aux Boiler", _fmt_fuel_line(boiler))
            _add_field(grid, 4, 0, "Total", _fmt_fuel_line(stage.consumption_mt))
        else:
            _add_field(grid, 1, 0, "ULSFO / VLSFO / MDO", _fmt_fuel_line(stage.consumption_mt))
            _add_field(grid, 2, 0, "Total", f"{stage.total_consumption_mt:.2f} MT")
        return frame

    def _rob_group(self, stage: OperationalStage) -> QFrame:
        frame, grid = _group("ROB")
        grid.addWidget(QLabel("Fuel"), 1, 0)
        grid.addWidget(QLabel("START"), 1, 1)
        grid.addWidget(QLabel("END"), 1, 2)
        for row, fuel_type in enumerate(FUEL_TYPES, start=2):
            _add_plain(grid, row, 0, fuel_type)
            _add_plain(grid, row, 1, _fmt_mt(stage.rob.start_mt[fuel_type]))
            _add_plain(grid, row, 2, _fmt_mt(stage.rob.end_mt[fuel_type]))
        return frame

    def _changeover_group(self, stage: OperationalStage) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
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
        dialog = StageEditDialog(stage, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
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
        self.status_label.setText("Voyage stage saved and downstream cards refreshed.")

    def _update_actual_rob(self, stage: OperationalStage) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            return
        dialog = ActualROBDialog(stage, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
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
            return
        self.refresh()
        self.status_label.setText("Actual ROB observation saved; future cards refreshed from the new anchor.")

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


class StageEditDialog(QDialog):
    def __init__(self, stage: OperationalStage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit {stage.title}")
        self._stage = stage
        self._actual_controls: dict[str, tuple[QCheckBox, QDateTimeEdit]] = {}
        self._spin_controls: dict[str, QDoubleSpinBox] = {}
        self._egb_control: QCheckBox | None = None

        layout = QVBoxLayout(self)
        form = QGridLayout()
        layout.addLayout(form)
        row = 0
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


class ActualROBDialog(QDialog):
    def __init__(self, stage: OperationalStage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Update Actual ROB")
        self._quantity_inputs: dict[str, QDoubleSpinBox] = {}
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        layout.addLayout(grid)
        self.time_input = QDateTimeEdit()
        self.time_input.setCalendarPopup(True)
        self.time_input.setDisplayFormat("dd MMM yyyy HH:mm")
        self.time_input.setDateTime(QDateTime(stage.start_utc or datetime.now()))
        grid.addWidget(QLabel("Observation Time UTC"), 0, 0)
        grid.addWidget(self.time_input, 0, 1)
        for row, fuel_type in enumerate(FUEL_TYPES, start=1):
            spinbox = _spinbox(" MT", 0, 999999, 1)
            spinbox.setValue(stage.rob.start_mt.get(fuel_type, 0.0))
            self._quantity_inputs[fuel_type] = spinbox
            grid.addWidget(QLabel(f"{fuel_type} Actual ROB"), row, 0)
            grid.addWidget(spinbox, row, 1)
        self.remarks_input = QComboBox()
        self.remarks_input.setEditable(True)
        self.remarks_input.addItem("")
        grid.addWidget(QLabel("Remarks"), 4, 0)
        grid.addWidget(self.remarks_input, 4, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[str, object]:
        return {
            "effective_at_utc": self.time_input.dateTime().toPython(),
            "ULSFO": self._quantity_inputs["ULSFO"].value(),
            "VLSFO": self._quantity_inputs["VLSFO"].value(),
            "MDO": self._quantity_inputs["MDO"].value(),
            "remarks": self.remarks_input.currentText().strip() or None,
        }


def _group(title: str) -> tuple[QFrame, QGridLayout]:
    frame = QFrame()
    frame.setObjectName("panel")
    grid = QGridLayout(frame)
    grid.setContentsMargins(14, 12, 14, 12)
    grid.setHorizontalSpacing(12)
    grid.addWidget(_section_label(title), 0, 0, 1, 3)
    return frame, grid


def _add_field(grid: QGridLayout, row: int, column: int, label_text: str, value_text: str) -> None:
    label = QLabel(label_text)
    label.setObjectName("fieldLabel")
    value = QLabel(value_text)
    value.setObjectName("mutedText")
    value.setWordWrap(True)
    grid.addWidget(label, row * 2 - 1, column)
    grid.addWidget(value, row * 2, column)


def _add_plain(grid: QGridLayout, row: int, column: int, text: str) -> None:
    label = QLabel(text)
    label.setObjectName("mutedText")
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


def _fmt_fuel_line(values: dict[str, float]) -> str:
    return "  |  ".join(f"{fuel} {values.get(fuel, 0.0):.2f} MT" for fuel in FUEL_TYPES)


def _fmt_mt(value: float) -> str:
    return f"{value:.1f} MT"


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


def _effective(value: float | None, default: float) -> float:
    return float(default if value is None else value)


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


def _as_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value
