from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt

from fuel_consumption_calculator.calculations.bunker_projection_engine import EventBunkerROBProjection
from fuel_consumption_calculator.calculations.rob_projection_engine import EventROBProjection
from fuel_consumption_calculator.ui.pages.bunker_page import BunkerProjectionTableModel
from fuel_consumption_calculator.ui.pages.consumption_page import _format_utc
from fuel_consumption_calculator.ui.pages.rob_page import ROBProjectionTableModel
from fuel_consumption_calculator.ui.pages.schedule_page import ScheduleTableModel


def test_user_facing_time_labels_are_explicit_and_readable():
    source = datetime(2026, 9, 6, 16, 30, tzinfo=timezone(timedelta(hours=8)))

    assert _format_utc(source) == "06 Sep 2026 08:30 UTC"
    assert ScheduleTableModel.HEADERS[3:5] == ("Arrival (Port LT)", "Departure (Port LT)")


def test_rob_projection_table_handles_unavailable_rob_without_coloring_crash():
    model = ROBProjectionTableModel()
    model.set_rows(
        [
            EventROBProjection(
                event_id=1,
                sequence_number=1,
                port="Santos",
                sea_hours=0.0,
                port_hours=0.0,
                consumed_mt={"ULSFO": None, "VLSFO": 0.0, "MDO": 0.0},
                cumulative_consumed_mt={"ULSFO": None, "VLSFO": 0.0, "MDO": 0.0},
                projected_rob_mt={"ULSFO": None, "VLSFO": 0.0, "MDO": 0.0},
            )
        ]
    )

    index = model.index(0, 3)

    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "—"
    assert model.data(index, Qt.ItemDataRole.ForegroundRole) is None


def test_bunker_projection_table_handles_unavailable_rob_without_coloring_crash():
    model = BunkerProjectionTableModel()
    model.set_rows(
        [
            EventBunkerROBProjection(
                event_id=1,
                sequence_number=1,
                port="Santos",
                sea_hours=0.0,
                port_hours=0.0,
                consumed_mt={"ULSFO": None, "VLSFO": 0.0, "MDO": 0.0},
                arrival_rob_mt={"ULSFO": None, "VLSFO": 0.0, "MDO": 0.0},
                bunker_mt={"ULSFO": 0.0, "VLSFO": 0.0, "MDO": 0.0},
                post_bunker_rob_mt={"ULSFO": None, "VLSFO": 0.0, "MDO": 0.0},
                departure_rob_mt={"ULSFO": None, "VLSFO": 0.0, "MDO": 0.0},
            )
        ]
    )

    index = model.index(0, 1)

    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "—"
    assert model.data(index, Qt.ItemDataRole.ForegroundRole) is None
