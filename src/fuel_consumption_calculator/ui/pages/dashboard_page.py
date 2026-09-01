from __future__ import annotations

from datetime import datetime, timezone
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from fuel_consumption_calculator.calculations.current_rob_engine import estimate_current_rob
from fuel_consumption_calculator.domain.voyage_stages import build_voyage_stage_timeline
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.rob_service import ROBService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.services.voyage_service import VoyageService
from fuel_consumption_calculator.ui.widgets.dashboard_components import DashboardCard, EmptyState, FuelRobCard, InfoMetricCard
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader


LOGGER = logging.getLogger(__name__)


class DashboardPage(QWidget):
    """Read-only operational overview assembled from existing service outputs."""

    open_voyage_requested = Signal()

    def __init__(
        self,
        vessel_service: VesselService,
        schedule_service: ScheduleService,
        consumption_service: ConsumptionService,
        voyage_service: VoyageService,
        rob_service: ROBService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vessel_service = vessel_service
        self._schedule_service = schedule_service
        self._consumption_service = consumption_service
        self._voyage_service = voyage_service
        self._rob_service = rob_service

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)
        layout.addWidget(PageHeader("Dashboard", "Current vessel and fuel-planning overview."))

        overview = QGridLayout()
        overview.setHorizontalSpacing(12)
        overview.setVerticalSpacing(12)
        overview.setColumnStretch(0, 2)
        overview.setColumnStretch(1, 5)

        self.vessel_card = DashboardCard("VESSEL")
        self.vessel_name_value = QLabel("Not configured")
        self.vessel_name_value.setObjectName("dashboardValue")
        self.imo_value = QLabel("IMO: -")
        self.imo_value.setObjectName("dashboardMeta")
        self.vessel_card.layout.addWidget(self.vessel_name_value)
        self.vessel_card.layout.addWidget(self.imo_value)
        self.vessel_card.layout.addStretch()
        overview.addWidget(self.vessel_card, 0, 0)

        self.rob_section = DashboardCard("CURRENT ROB")
        rob_cards = QHBoxLayout()
        rob_cards.setContentsMargins(0, 0, 0, 0)
        rob_cards.setSpacing(9)
        self._rob_cards = {fuel: FuelRobCard(fuel) for fuel in ("ULSFO", "VLSFO", "MDO")}
        self._rob_values = {fuel: card.value_label for fuel, card in self._rob_cards.items()}
        for card in self._rob_cards.values():
            rob_cards.addWidget(card, 1)
        self.rob_section.layout.addLayout(rob_cards)
        self.rob_metadata = QLabel("Calculated to: -  |  Anchor: Projection Starting ROB")
        self.rob_metadata.setObjectName("dashboardMeta")
        self.rob_section.layout.addWidget(self.rob_metadata)
        overview.addWidget(self.rob_section, 0, 1)
        layout.addLayout(overview)

        metric_row = QHBoxLayout()
        metric_row.setSpacing(12)
        self.next_port_card = InfoMetricCard("NEXT PORT")
        self.schedule_status_card = InfoMetricCard("SCHEDULE STATUS")
        self.rob_status_card = InfoMetricCard("ROB STATUS")
        for card in (self.next_port_card, self.schedule_status_card, self.rob_status_card):
            metric_row.addWidget(card, 1)
        layout.addLayout(metric_row)

        self.schedule_section = DashboardCard("UPCOMING VOYAGE / SCHEDULE")
        self.schedule_table = QTableWidget(0, 5)
        self.schedule_table.setObjectName("dashboardTable")
        self.schedule_table.setHorizontalHeaderLabels(("Event", "Port", "Arrival", "Departure", "Source"))
        self.schedule_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.schedule_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.schedule_table.setAlternatingRowColors(True)
        self.schedule_table.verticalHeader().setVisible(False)
        self.schedule_table.horizontalHeader().setStretchLastSection(True)
        self.schedule_table.setMinimumHeight(150)
        self.schedule_empty = EmptyState("No schedule available. Add or update schedule events to see the operational preview.")
        self.schedule_section.layout.addWidget(self.schedule_table)
        self.schedule_section.layout.addWidget(self.schedule_empty)
        footer = QHBoxLayout()
        footer.addStretch()
        self.open_voyage_button = QPushButton("Open Voyage Planner")
        self.open_voyage_button.clicked.connect(self.open_voyage_requested.emit)
        footer.addWidget(self.open_voyage_button)
        self.schedule_section.layout.addLayout(footer)
        layout.addWidget(self.schedule_section, 1)

        self.status_label = EmptyState("")
        layout.addWidget(self.status_label)
        self.refresh()

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self._set_rob(None, None, None)
            self.vessel_name_value.setText("Not configured")
            self.imo_value.setText("IMO: -")
            self.next_port_card.set_data("Unavailable", "Configure a vessel to load schedule data.")
            self.schedule_status_card.set_data("No schedule", "No vessel configured")
            self.rob_status_card.set_data("Unavailable", "No vessel configured")
            self._set_schedule_preview(())
            self.status_label.setText("No vessel configured. Open Settings to get started.")
            self.status_label.show()
            return

        self.vessel_name_value.setText(vessel.name)
        self.imo_value.setText(f"IMO: {vessel.imo or '-'}")
        try:
            events = tuple(self._schedule_service.list_events(vessel.id))
        except Exception:
            LOGGER.exception("Dashboard schedule preview could not be loaded.")
            events = ()
        self._set_schedule_preview(events)
        self._refresh_current_rob(vessel.id, events)

    def _set_schedule_preview(self, events) -> None:
        now = datetime.now(timezone.utc)
        ordered = sorted(events, key=lambda event: _utc_instant(event.effective_arrival_at))
        future = [event for event in ordered if _utc_instant(event.effective_arrival_at) >= now]
        preview = (future or ordered)[:6]
        self.schedule_table.setRowCount(0)
        for row, event in enumerate(preview):
            self.schedule_table.insertRow(row)
            values = (
                event.event_type or "-",
                event.port or "-",
                _format_time(event.effective_arrival_at),
                _format_time(event.effective_departure_at),
                event.source or "-",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {2, 3}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.schedule_table.setItem(row, column, item)

        has_events = bool(preview)
        self.schedule_table.setVisible(has_events)
        self.schedule_empty.setVisible(not has_events)
        if not events:
            self.next_port_card.set_data("Unavailable", "No schedule events available")
            self.schedule_status_card.set_data("No schedule", "Add or update schedule events")
            return
        next_event = (future or ordered)[0]
        self.next_port_card.set_data(next_event.port or "-", f"{next_event.event_type or 'Event'}  |  {_format_time(next_event.effective_arrival_at)}")
        self.schedule_status_card.set_data(f"{len(events)} event{'s' if len(events) != 1 else ''}", "Showing the next operational events")

    def _refresh_current_rob(self, vessel_id: int, events) -> None:
        now = datetime.now(timezone.utc)
        try:
            observations = self._voyage_service.list_actual_rob_observations(vessel_id)
            actual = _latest_applicable_actual(observations, now)
            schedule_timeline = self._schedule_service.get_timeline(vessel_id)
            if schedule_timeline.issues:
                raise ValueError("Schedule chronology needs attention")
            profile = self._consumption_service.load_profile(vessel_id)
            plan = self._voyage_service.calculate_plan(vessel_id, list(events), profile)
            result = self._voyage_service.calculate_consumption_for_plan(events=list(events), timeline=schedule_timeline, plan=plan, profile=profile)
            timeline = build_voyage_stage_timeline(events, plan, self._rob_service.load_starting_rob(vessel_id), port_breakdowns=result.port_breakdowns, rob_observations=observations, now_utc=now)
            if actual is not None:
                estimated = estimate_current_rob(anchor_quantities_mt=actual.quantities_mt, anchor_at_utc=actual.effective_at_utc, current_utc=now, stages=timeline.stages, initial_fuel_state=plan.initial_fuel_state, fuel_changeovers=plan.fuel_changeovers, energy_config=plan.energy_config)
                self._set_rob(estimated, now, actual.effective_at_utc)
                self.rob_status_card.set_data("Estimated", "Latest Actual ROB anchor")
                self.status_label.hide()
                return
            starting_rob = self._rob_service.load_starting_rob(vessel_id)
            starting_quantities = {fuel: starting_rob.quantity_for(fuel) for fuel in self._rob_values}
            stage_starts = [_utc_instant(stage.start_utc) for stage in timeline.stages if stage.start_utc is not None]
            projection_start = min(stage_starts, default=now)
            estimated = estimate_current_rob(anchor_quantities_mt=starting_quantities, anchor_at_utc=projection_start, current_utc=now, stages=timeline.stages, initial_fuel_state=plan.initial_fuel_state, fuel_changeovers=plan.fuel_changeovers, energy_config=plan.energy_config)
            self._set_rob(estimated, now, None)
            self.rob_status_card.set_data("Estimated", "Projection Starting ROB anchor")
            self.status_label.hide()
            return
        except Exception:
            LOGGER.exception("Estimated Current ROB could not be calculated.")
        self._set_rob(None, None, None)
        self.rob_status_card.set_data("Unavailable", "Current ROB could not be calculated")
        self.status_label.setText("Current ROB is unavailable.")
        self.status_label.show()

    def _set_rob(self, quantities: dict[str, float | None] | None, calculated_at_utc: datetime | None, actual_anchor_at_utc: datetime | None) -> None:
        metadata = f"Calculated {_format_time(calculated_at_utc)}" if calculated_at_utc else "Unavailable"
        for fuel, card in self._rob_cards.items():
            value = quantities.get(fuel) if quantities is not None else None
            card.set_value(value, metadata)
        calculated = _format_time(calculated_at_utc) if calculated_at_utc else "-"
        anchor = _format_time(actual_anchor_at_utc) if actual_anchor_at_utc else "Projection Starting ROB"
        self.rob_metadata.setText(f"Calculated to: {calculated}  |  Anchor: {anchor}")


def _format_time(value: datetime | None) -> str:
    if value is None:
        return "-"
    return _utc_instant(value).strftime("%d %b %Y %H:%M UTC")


def _utc_instant(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _latest_applicable_actual(observations, target_utc: datetime):
    return max((item for item in observations if _utc_instant(item.effective_at_utc) <= _utc_instant(target_utc)), key=lambda item: _utc_instant(item.effective_at_utc), default=None)
