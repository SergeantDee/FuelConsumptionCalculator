from __future__ import annotations

from datetime import datetime, timezone
import logging

from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from fuel_consumption_calculator.calculations.current_rob_engine import estimate_current_rob
from fuel_consumption_calculator.domain.voyage_stages import build_voyage_stage_timeline
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.rob_service import ROBService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.services.voyage_service import VoyageService
from fuel_consumption_calculator.ui.widgets.page_header import PageHeader
from fuel_consumption_calculator.ui.widgets.fuel_display import FuelBadge


LOGGER = logging.getLogger(__name__)


class DashboardPage(QWidget):
    def __init__(self, vessel_service: VesselService, schedule_service: ScheduleService, consumption_service: ConsumptionService, voyage_service: VoyageService, rob_service: ROBService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vessel_service = vessel_service
        self._schedule_service = schedule_service
        self._consumption_service = consumption_service
        self._voyage_service = voyage_service
        self._rob_service = rob_service

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)
        layout.addWidget(PageHeader("Dashboard", "Current vessel and fuel-planning overview."))

        identity = QFrame()
        identity.setObjectName("card")
        identity_layout = QGridLayout(identity)
        identity_layout.setContentsMargins(20, 18, 20, 18)
        identity_layout.addWidget(self._label("VESSEL"), 0, 0)
        identity_layout.addWidget(self._label("IMO NUMBER"), 0, 1)
        self.vessel_name_value = QLabel("Not configured")
        self.vessel_name_value.setObjectName("cardValue")
        self.imo_value = QLabel("—")
        self.imo_value.setObjectName("cardValue")
        identity_layout.addWidget(self.vessel_name_value, 1, 0)
        identity_layout.addWidget(self.imo_value, 1, 1)
        layout.addWidget(identity)

        fuel_cards = QHBoxLayout()
        fuel_cards.setSpacing(14)
        self._rob_values: dict[str, QLabel] = {}
        estimated_title = QLabel("CURRENT ROB")
        estimated_title.setObjectName("sectionTitle")
        layout.addWidget(estimated_title)
        for fuel in ("ULSFO", "VLSFO", "MDO"):
            fuel_cards.addWidget(self._fuel_card(fuel))
        layout.addLayout(fuel_cards)
        self.rob_metadata = QLabel("As of: -  |  Source: -")
        self.rob_metadata.setObjectName("mutedText")
        layout.addWidget(self.rob_metadata)

        self.status_label = QLabel()
        layout.addWidget(self.status_label)
        layout.addStretch()
        self.refresh()

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("cardLabel")
        return label

    def _fuel_card(self, fuel: str) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.addWidget(FuelBadge(fuel))
        value = QLabel("— MT")
        value.setObjectName("cardValue")
        card_layout.addWidget(value)
        self._rob_values[fuel] = value
        return card

    def refresh(self) -> None:
        vessel = self._vessel_service.get_active_vessel()
        if vessel is None:
            self._set_rob(None, None, None)
            self.vessel_name_value.setText("Not configured")
            self.imo_value.setText("—")
            self.status_label.setText("Vessel not configured — open Settings to get started.")
            self.status_label.setObjectName("notConfiguredStatus")
        else:
            self.vessel_name_value.setText(vessel.name)
            self.imo_value.setText(vessel.imo)
            self._refresh_current_rob(vessel.id)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _refresh_current_rob(self, vessel_id: int) -> None:
        now = datetime.now(timezone.utc)
        try:
            observations = self._voyage_service.list_actual_rob_observations(vessel_id)
            actual = _latest_applicable_actual(observations, now)
            events = self._schedule_service.list_events(vessel_id)
            schedule_timeline = self._schedule_service.get_timeline(vessel_id)
            if schedule_timeline.issues:
                raise ValueError("Schedule chronology needs attention")
            profile = self._consumption_service.load_profile(vessel_id)
            plan = self._voyage_service.calculate_plan(vessel_id, events, profile)
            result = self._voyage_service.calculate_consumption_for_plan(events=events, timeline=schedule_timeline, plan=plan, profile=profile)
            timeline = build_voyage_stage_timeline(events, plan, self._rob_service.load_starting_rob(vessel_id), port_breakdowns=result.port_breakdowns, rob_observations=observations, now_utc=now)
            if actual is not None:
                estimated = estimate_current_rob(
                    anchor_quantities_mt=actual.quantities_mt,
                    anchor_at_utc=actual.effective_at_utc,
                    current_utc=now,
                    stages=timeline.stages,
                    initial_fuel_state=plan.initial_fuel_state,
                    fuel_changeovers=plan.fuel_changeovers,
                    energy_config=plan.energy_config,
                )
                self._set_rob(estimated, now, actual.effective_at_utc)
                self.status_label.setText("Estimated Current ROB is calculated from the latest Actual ROB anchor.")
                self.status_label.setObjectName("configuredStatus")
                return
            starting_rob = self._rob_service.load_starting_rob(vessel_id)
            starting_quantities = {fuel: starting_rob.quantity_for(fuel) for fuel in self._rob_values}
            stage_starts = [_utc_instant(stage.start_utc) for stage in timeline.stages if stage.start_utc is not None]
            projection_start = min(stage_starts, default=now)
            estimated = estimate_current_rob(
                anchor_quantities_mt=starting_quantities,
                anchor_at_utc=projection_start,
                current_utc=now,
                stages=timeline.stages,
                initial_fuel_state=plan.initial_fuel_state,
                fuel_changeovers=plan.fuel_changeovers,
                energy_config=plan.energy_config,
            )
            self._set_rob(estimated, now, None)
            self.status_label.setText("Estimated Current ROB is calculated from the Projection Starting ROB anchor.")
            self.status_label.setObjectName("configuredStatus")
            return
        except Exception:
            LOGGER.exception("Estimated Current ROB could not be calculated.")
        self._set_rob(None, None, None)
        self.status_label.setText("Current ROB is unavailable.")
        self.status_label.setObjectName("notConfiguredStatus")

    def _set_rob(self, quantities: dict[str, float | None] | None, calculated_at_utc: datetime | None, actual_anchor_at_utc: datetime | None) -> None:
        for fuel, label in self._rob_values.items():
            value = quantities.get(fuel) if quantities is not None else None
            label.setText(f"{float(value):.2f} MT" if value is not None else "- MT")
        calculated = calculated_at_utc.astimezone(timezone.utc).strftime("%d %b %Y %H:%M UTC") if calculated_at_utc else "-"
        anchor = actual_anchor_at_utc.astimezone(timezone.utc).strftime("%d %b %Y %H:%M UTC") if actual_anchor_at_utc else "-"
        anchor_text = f"Actual Sounding ROB {anchor}" if actual_anchor_at_utc else "Projection Starting ROB"
        self.rob_metadata.setText(f"Calculated to: {calculated}  |  Anchor: {anchor_text}")



def _utc_instant(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _latest_applicable_actual(observations, target_utc: datetime):
    """Return the newest historical sounding; future soundings cannot be anchors."""
    return max(
        (item for item in observations if _utc_instant(item.effective_at_utc) <= _utc_instant(target_utc)),
        key=lambda item: _utc_instant(item.effective_at_utc),
        default=None,
    )
