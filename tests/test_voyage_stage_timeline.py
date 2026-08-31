from __future__ import annotations

import os
from datetime import date, datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QTabWidget

from fuel_consumption_calculator.calculations.voyage_engine import calculate_consumption_with_voyage, calculate_voyage_consumption, calculate_voyage_plan
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES, ConsumptionProfile, ConsumptionRate
from fuel_consumption_calculator.domain.rob import ROBQuantity, StartingROB
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.schedule_timeline import build_schedule_timeline
from fuel_consumption_calculator.domain.voyage import (
    ActualROBObservation,
    FuelChangeoverEvent,
    GeneratorSfocPoint,
    MachineryFuelState,
    RouteDefinition,
    VesselEnergyConfig,
    VoyageLeg,
    VoyageLegOverride,
)
from fuel_consumption_calculator.domain.voyage_stages import (
    STATUS_COMPLETED,
    STATUS_CURRENT,
    STAGE_ARRIVAL_MANEUVERING,
    STAGE_DEPARTURE_MANEUVERING,
    STAGE_PORT_STAY,
    STAGE_SEA_PASSAGE,
    build_voyage_stage_timeline,
)
from fuel_consumption_calculator.ui.pages.voyage_page import (
    StageEditDialog,
    VoyagePage,
    build_planner_display_rows,
    _fmt_compact_rob,
    _stage_issue,
)
from fuel_consumption_calculator.ui.pages.dashboard_page import DashboardPage, _latest_applicable_actual
from fuel_consumption_calculator.ui.pages.bunker_page import BunkerPage
import fuel_consumption_calculator.ui.pages.bunker_page as bunker_page_module
from fuel_consumption_calculator.ui.widgets.actual_rob_dialog import ActualROBDialog


def test_stage_timeline_uses_port_departure_sea_arrival_sequence():
    events = _events()
    plan = _plan()
    calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())

    timeline = build_voyage_stage_timeline(events, plan, _starting_rob(), now_utc=datetime(2025, 12, 30, tzinfo=timezone.utc))

    assert [stage.stage_type for stage in timeline.stages] == [
        STAGE_PORT_STAY,
        STAGE_DEPARTURE_MANEUVERING,
        STAGE_SEA_PASSAGE,
        STAGE_ARRIVAL_MANEUVERING,
        STAGE_PORT_STAY,
    ]
    assert timeline.stages[0].rob.end_mt == timeline.stages[1].rob.start_mt


def test_voyage_main_table_uses_operational_fuel_total_not_machinery_columns():
    assert "Total Consumption" in VoyagePage.TABLE_COLUMNS
    assert "Calculated Speed" in VoyagePage.TABLE_COLUMNS
    assert "EOE ROB" in VoyagePage.TABLE_COLUMNS
    assert not {"Main Engine", "Auxiliary Engines", "Auxiliary Boiler"}.intersection(VoyagePage.TABLE_COLUMNS)


def test_pre_voyage_timeline_keeps_current_rob_at_starting_anchor():
    events = _events()
    plan = _plan()
    calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())

    timeline = build_voyage_stage_timeline(events, plan, _starting_rob(), now_utc=datetime(2025, 12, 30, tzinfo=timezone.utc))

    assert timeline.current_stage is None
    assert timeline.current_predicted_rob_mt == {"ULSFO": 100.0, "VLSFO": 100.0, "MDO": 100.0}
    assert timeline.next_port == "Origin"


def test_actual_departure_moves_port_stay_to_completed_and_departure_to_current():
    events = _events()
    override = VoyageLegOverride(
        1,
        2,
        "Origin",
        "Destination",
        "2026-01-01T00:00+00:00",
        "2026-01-02T12:00+00:00",
        actual_berth_departure=datetime(2026, 1, 1, 0, tzinfo=timezone.utc),
    )
    plan = _plan(override)
    calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())

    timeline = build_voyage_stage_timeline(events, plan, _starting_rob(), now_utc=datetime(2026, 1, 1, 1, tzinfo=timezone.utc))

    assert timeline.stages[0].status == STATUS_COMPLETED
    assert timeline.stages[1].status == STATUS_CURRENT
    assert timeline.current_stage is timeline.stages[1]


def test_stage_changeovers_include_actual_timestamp_and_do_not_create_default_events():
    events = _events()
    changeover = FuelChangeoverEvent(
        None,
        1,
        "MAIN_ENGINE",
        "VLSFO",
        "ULSFO",
        planned_at_utc=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        actual_at_utc=datetime(2026, 1, 1, 18, tzinfo=timezone.utc),
    )
    plan = _plan(changeovers=[changeover], detailed=True)
    calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())

    timeline = build_voyage_stage_timeline(events, plan, _starting_rob(), now_utc=datetime(2025, 12, 30, tzinfo=timezone.utc))
    sea_stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_SEA_PASSAGE)

    assert sea_stage.changeovers == (changeover,)
    assert sea_stage.changeovers[0].effective_at_utc == datetime(2026, 1, 1, 18, tzinfo=timezone.utc)


def test_actual_rob_observation_resets_downstream_forecast_anchor():
    events = _events()
    plan = _plan()
    calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())
    observation = ActualROBObservation(
        None,
        1,
        datetime(2026, 1, 1, 2, tzinfo=timezone.utc),
        {"ULSFO": 90.0, "VLSFO": 80.0, "MDO": 70.0},
    )

    timeline = build_voyage_stage_timeline(events, plan, _starting_rob(), now_utc=datetime(2025, 12, 30, tzinfo=timezone.utc), rob_observations=[observation])

    departure_stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_DEPARTURE_MANEUVERING)
    sea_stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_SEA_PASSAGE)
    assert departure_stage.rob.end_mt == {"ULSFO": 90.0, "VLSFO": 80.0, "MDO": 70.0}
    assert sea_stage.rob.start_mt == departure_stage.rob.end_mt


def test_actual_rob_observation_inside_sea_stage_splits_remaining_consumption():
    events = _events()
    changeover = FuelChangeoverEvent(None, 1, "MAIN_ENGINE", "VLSFO", "ULSFO", datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
    plan = _plan(changeovers=[changeover], detailed=True)
    calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())
    observation = ActualROBObservation(
        None,
        1,
        datetime(2026, 1, 1, 18, tzinfo=timezone.utc),
        {"ULSFO": 50.0, "VLSFO": 60.0, "MDO": 70.0},
    )

    timeline = build_voyage_stage_timeline(events, plan, _starting_rob(), now_utc=datetime(2025, 12, 30, tzinfo=timezone.utc), rob_observations=[observation])

    sea_stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_SEA_PASSAGE)
    assert sea_stage.rob.end_mt["VLSFO"] < 60.0
    assert sea_stage.rob.end_mt["ULSFO"] <= 50.0


def test_actual_rob_observation_restores_forecast_after_unknown_stage():
    events = _events()
    plan = _plan()
    calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())
    observation = ActualROBObservation(
        None,
        1,
        datetime(2026, 1, 2, 11, tzinfo=timezone.utc),
        {"ULSFO": 70.0, "VLSFO": 80.0, "MDO": 90.0},
    )

    timeline = build_voyage_stage_timeline(events, plan, _starting_rob(), now_utc=datetime(2025, 12, 30, tzinfo=timezone.utc), rob_observations=[observation])

    sea_stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_SEA_PASSAGE)
    arrival_stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_ARRIVAL_MANEUVERING)
    assert sea_stage.rob.end_mt == {"ULSFO": None, "VLSFO": None, "MDO": None}
    assert arrival_stage.rob.start_mt == {"ULSFO": None, "VLSFO": None, "MDO": None}
    assert arrival_stage.rob.end_mt["ULSFO"] == 70.0


def test_actual_rob_observation_reanchors_after_unknown_detailed_departure_maneuvering():
    events = _events()
    plan = _plan(detailed=True)
    observation = ActualROBObservation(
        None,
        1,
        datetime(2026, 1, 1, 2, tzinfo=timezone.utc),
        {"ULSFO": 70.0, "VLSFO": 80.0, "MDO": 90.0},
    )

    timeline = build_voyage_stage_timeline(
        events,
        plan,
        _starting_rob(),
        now_utc=datetime(2025, 12, 30, tzinfo=timezone.utc),
        rob_observations=[observation],
    )

    departure_stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_DEPARTURE_MANEUVERING)
    sea_stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_SEA_PASSAGE)
    assert departure_stage.rob.end_mt == {"ULSFO": 70.0, "VLSFO": 80.0, "MDO": 90.0}
    assert sea_stage.rob.start_mt == departure_stage.rob.end_mt


def test_confirmed_port_bunker_adjustment_is_applied_by_the_existing_stage_timeline():
    events = _events()
    timeline = build_voyage_stage_timeline(
        events,
        _plan(),
        _starting_rob(),
        port_bunker_additions={events[0].id: {"ULSFO": 0.0, "VLSFO": 25.0, "MDO": 0.0}},
    )
    origin_port = next(stage for stage in timeline.stages if stage.key == "port-1")

    assert origin_port.rob.start_mt["VLSFO"] == 100.0
    assert origin_port.rob.end_mt["VLSFO"] == 125.0


def test_voyage_detail_dialog_uses_event_consumption_and_rob_tabs():
    app = QApplication.instance() or QApplication([])
    events = _events()
    timeline = build_voyage_stage_timeline(events, _plan(), _starting_rob())
    stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_SEA_PASSAGE)

    dialog = StageEditDialog(stage, None)

    tabs = dialog.findChild(QTabWidget)
    assert app is not None
    assert tabs is not None
    assert [tabs.tabText(index) for index in range(tabs.count())] == ["Event", "Consumption", "ROB"]


def test_voyage_grid_helpers_keep_unknown_rob_and_flag_missing_sea_distance():
    override = VoyageLegOverride(
        1,
        2,
        "Origin",
        "Destination",
        "2026-01-01T00:00+00:00",
        "2026-01-02T12:00+00:00",
        sea_distance_nm=0.0,
    )
    timeline = build_voyage_stage_timeline(_events(), _plan(override), _starting_rob())
    sea_stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_SEA_PASSAGE)

    assert _stage_issue(sea_stage) == "Missing sea distance"
    assert _fmt_compact_rob({"ULSFO": None, "VLSFO": 2.5, "MDO": None}) == "ULSFO -  |  VLSFO 2.50  |  MDO -"


def test_actual_rob_dialog_accepts_zero_for_every_fuel():
    QApplication.instance() or QApplication([])
    dialog = ActualROBDialog({"ULSFO": 0.0, "VLSFO": 0.0, "MDO": 0.0})

    dialog.accept()

    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.values()["ULSFO"] == 0.0
    assert dialog.values()["VLSFO"] == 0.0
    assert dialog.values()["MDO"] == 0.0
    assert dialog.values()["effective_at_utc"].tzinfo == timezone.utc


def test_dashboard_keeps_rob_unavailable_when_elapsed_consumption_cannot_be_calculated():
    QApplication.instance() or QApplication([])
    older = ActualROBObservation(None, 1, datetime(2026, 1, 1, tzinfo=timezone.utc), {"ULSFO": 1.0, "VLSFO": 2.0, "MDO": 3.0})
    latest = ActualROBObservation(None, 1, datetime(2026, 1, 2, tzinfo=timezone.utc), {"ULSFO": 4.0, "VLSFO": 5.0, "MDO": 6.0})

    page = DashboardPage(
        _ActiveVesselService(),
        object(),
        object(),
        _ActualROBVoyageService([older, latest]),
        object(),
    )

    assert page._rob_values["ULSFO"].text() == "- MT"
    assert "Anchor: Projection Starting ROB" in page.rob_metadata.text()
    assert not hasattr(page, "update_rob_button")
    assert any(label.text() == "CURRENT ROB" for label in page.findChildren(QLabel))


def test_dashboard_anchor_ignores_future_actual_sounding():
    earlier = ActualROBObservation(None, 1, datetime(2026, 1, 1, tzinfo=timezone.utc), {"ULSFO": 1.0, "VLSFO": 2.0, "MDO": 3.0})
    later = ActualROBObservation(None, 1, datetime(2026, 1, 3, tzinfo=timezone.utc), {"ULSFO": 4.0, "VLSFO": 5.0, "MDO": 6.0})

    assert _latest_applicable_actual([earlier, later], datetime(2026, 1, 2, tzinfo=timezone.utc)) == earlier


def test_bunker_actual_sounding_uses_existing_actual_rob_persistence(monkeypatch):
    QApplication.instance() or QApplication([])
    class _SwitchableVesselService:
        active = None

        def get_active_vessel(self):
            return self.active

    vessel_service = _SwitchableVesselService()
    voyage_service = _SavingActualROBVoyageService()
    page = BunkerPage(vessel_service, object(), object(), object(), object(), voyage_service)
    assert page.update_sounding_button.text() == "Update Actual Sounding ROB"
    vessel_service.active = type("Vessel", (), {"id": 1, "name": "Test Vessel", "imo": "1234567"})()
    page.refresh = lambda: None
    saved_signal = []
    page.actual_sounding_saved.connect(lambda: saved_signal.append(True))

    class _Dialog:
        def __init__(self, quantities_mt, parent):
            assert quantities_mt is None

        def exec(self):
            return QDialog.DialogCode.Accepted

        @staticmethod
        def values():
            return {
                "effective_at_utc": datetime(2026, 1, 3, 12, tzinfo=timezone.utc),
                "ULSFO": 10.0,
                "VLSFO": 20.0,
                "MDO": 30.0,
                "remarks": "Noon sounding",
            }

    monkeypatch.setattr(bunker_page_module, "ActualROBDialog", _Dialog)

    page._update_actual_sounding()

    assert voyage_service.saved == ActualROBObservation(
        None,
        1,
        datetime(2026, 1, 3, 12, tzinfo=timezone.utc),
        {"ULSFO": 10.0, "VLSFO": 20.0, "MDO": 30.0},
        "Noon sounding",
    )
    assert saved_signal == [True]


def test_planner_display_groups_simultaneous_changeovers_at_effective_timestamp():
    planned = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    actual = datetime(2026, 1, 1, 18, tzinfo=timezone.utc)
    events = [
        FuelChangeoverEvent(None, 1, machinery, "VLSFO", "ULSFO", planned, actual_at_utc=actual)
        for machinery in ("MAIN_ENGINE", "GENERATORS", "AUX_BOILER")
    ]

    rows = build_planner_display_rows([], tuple(events))

    assert len(rows) == 1
    assert rows[0].timestamp == actual
    assert len(rows[0].changeovers) == 3


def test_planner_display_keeps_non_simultaneous_changeovers_separate_and_ordered():
    first = FuelChangeoverEvent(None, 1, "MAIN_ENGINE", "VLSFO", "ULSFO", datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
    second = FuelChangeoverEvent(None, 1, "GENERATORS", "VLSFO", "ULSFO", datetime(2026, 1, 1, 13, tzinfo=timezone.utc))

    rows = build_planner_display_rows([], (second, first))

    assert [row.timestamp for row in rows] == [first.effective_at_utc, second.effective_at_utc]


class _ActiveVesselService:
    def get_active_vessel(self):
        return type("Vessel", (), {"id": 1, "name": "Test Vessel", "imo": "1234567"})()


class _ActualROBVoyageService:
    def __init__(self, observations):
        self._observations = observations

    def list_actual_rob_observations(self, vessel_id):
        return self._observations


class _SavingActualROBVoyageService(_ActualROBVoyageService):
    def __init__(self):
        super().__init__([])
        self.saved = None

    def save_actual_rob_observation(self, observation):
        self.saved = observation
        return observation


def _plan(override: VoyageLegOverride | None = None, changeovers: list[FuelChangeoverEvent] | None = None, detailed: bool = False):
    leg = VoyageLeg(
        vessel_id=1,
        sequence_number=2,
        origin_event_id=1,
        destination_event_id=2,
        origin_port="Origin",
        destination_port="Destination",
        scheduled_berth_departure=datetime(2026, 1, 1, 0, tzinfo=timezone.utc),
        scheduled_berth_arrival=datetime(2026, 1, 2, 12, tzinfo=timezone.utc),
        route=RouteDefinition("Origin", "Destination", 5, 2, 320, 5, 2),
        override=override,
    )
    return calculate_voyage_plan(
        [leg],
        _profile(),
        [],
        _energy_config() if detailed else None,
        _sfoc_points() if detailed else None,
        initial_fuel_state=MachineryFuelState(1, "VLSFO", "VLSFO", "VLSFO"),
        fuel_changeovers=changeovers or [],
    )


def _events() -> list[ScheduleEvent]:
    return [
        ScheduleEvent(
            1,
            1,
            1,
            "Origin",
            "Port Call",
            datetime(2025, 12, 31, 12),
            datetime(2026, 1, 1, 0),
            "manual",
            "Fixture",
            date(2026, 1, 1),
            "",
            "",
            port_timezone_id="UTC",
            arrival_at_utc=datetime(2025, 12, 31, 12, tzinfo=timezone.utc),
            departure_at_utc=datetime(2026, 1, 1, 0, tzinfo=timezone.utc),
        ),
        ScheduleEvent(
            2,
            1,
            2,
            "Destination",
            "Port Call",
            datetime(2026, 1, 2, 12),
            None,
            "manual",
            "Fixture",
            date(2026, 1, 1),
            "",
            "",
            port_timezone_id="UTC",
            arrival_at_utc=datetime(2026, 1, 2, 12, tzinfo=timezone.utc),
        ),
    ]


def _profile() -> ConsumptionProfile:
    return ConsumptionProfile(
        1,
        tuple(
            ConsumptionRate(mode, fuel, 24.0 if fuel == "VLSFO" else 0.0)
            for mode in ("SEA", "MANEUVERING", "PORT")
            for fuel in FUEL_TYPES
        ),
    )


def _starting_rob() -> StartingROB:
    return StartingROB(1, tuple(ROBQuantity(fuel, 100.0) for fuel in FUEL_TYPES))


def _energy_config() -> VesselEnergyConfig:
    return VesselEnergyConfig(
        vessel_id=1,
        sea_base_load_kw=1000,
        generator_rated_kw=5000,
        sea_running_generators=1,
        aux_boiler_mt_per_hour=0.1,
        generator_fuel_type="VLSFO",
        boiler_fuel_type="MDO",
    )


def _sfoc_points() -> list[GeneratorSfocPoint]:
    return [GeneratorSfocPoint(1, 0, 220), GeneratorSfocPoint(1, 100, 200)]

def test_stage_timeline_does_not_require_prior_consumption_mutation():
    events = _events()
    plan = _plan()
    voyage_result = calculate_voyage_consumption(
        build_schedule_timeline(events),
        events,
        plan,
        _profile(),
    )

    timeline = build_voyage_stage_timeline(
        events,
        plan,
        _starting_rob(),
        port_breakdowns=voyage_result.port_breakdowns,
        now_utc=datetime(2025, 12, 30, tzinfo=timezone.utc),
    )

    first_port = next(stage for stage in timeline.stages if stage.stage_type == STAGE_PORT_STAY)
    expected_port_consumption = voyage_result.port_breakdowns[events[0].id].total_consumed_mt

    assert first_port.consumption_mt == expected_port_consumption
    assert events[0].id in voyage_result.port_breakdowns
    assert not hasattr(plan, "port_breakdowns")
