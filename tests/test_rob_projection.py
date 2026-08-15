from __future__ import annotations

from fuel_consumption_calculator.calculations.consumption_engine import EventFuelConsumption, ScheduleFuelConsumption
from fuel_consumption_calculator.calculations.rob_projection_engine import project_schedule_rob
from fuel_consumption_calculator.domain.rob import ROBQuantity, StartingROB
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.rob_repository import ROBRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.rob_service import ROBService


def starting_rob(ulsfo: float = 0.0, vlsfo: float = 0.0, mdo: float = 0.0) -> StartingROB:
    return StartingROB(
        vessel_id=1,
        quantities=(
            ROBQuantity("ULSFO", ulsfo),
            ROBQuantity("VLSFO", vlsfo),
            ROBQuantity("MDO", mdo),
        ),
    )


def consumption_row(sequence: int, *, ulsfo: float | None = 0.0, vlsfo: float | None = 0.0, mdo: float | None = 0.0) -> EventFuelConsumption:
    return EventFuelConsumption(
        event_id=sequence,
        sequence_number=sequence,
        port=f"Port {sequence}",
        sea_hours=0.0,
        port_hours=0.0,
        consumed_mt={"ULSFO": ulsfo, "VLSFO": vlsfo, "MDO": mdo},
    )


def consumption_result(rows: list[EventFuelConsumption]) -> ScheduleFuelConsumption:
    return ScheduleFuelConsumption(
        rows=rows,
        totals_mt={
            "ULSFO": None if any(row.consumed_mt["ULSFO"] is None for row in rows) else sum(row.consumed_mt["ULSFO"] for row in rows),
            "VLSFO": None if any(row.consumed_mt["VLSFO"] is None for row in rows) else sum(row.consumed_mt["VLSFO"] for row in rows),
            "MDO": None if any(row.consumed_mt["MDO"] is None for row in rows) else sum(row.consumed_mt["MDO"] for row in rows),
        },
    )


def test_rob_projection_subtracts_single_event_consumption():
    projection = project_schedule_rob(starting_rob(ulsfo=100), consumption_result([consumption_row(1, ulsfo=10)]))

    assert projection.rows[0].projected_rob_mt["ULSFO"] == 90
    assert projection.final_rob_mt["ULSFO"] == 90


def test_rob_projection_is_cumulative_across_events():
    projection = project_schedule_rob(
        starting_rob(ulsfo=100),
        consumption_result([consumption_row(1, ulsfo=10), consumption_row(2, ulsfo=20)]),
    )

    assert [row.projected_rob_mt["ULSFO"] for row in projection.rows] == [90, 70]
    assert projection.rows[1].cumulative_consumed_mt["ULSFO"] == 30


def test_rob_projection_keeps_fuels_independent_and_allows_negative_values():
    projection = project_schedule_rob(
        starting_rob(ulsfo=5, vlsfo=100, mdo=50),
        consumption_result([consumption_row(1, ulsfo=10, vlsfo=20, mdo=5)]),
    )

    assert projection.final_rob_mt == {"ULSFO": -5.0, "VLSFO": 80.0, "MDO": 45.0}


def test_unknown_consumption_makes_current_and_future_rob_unavailable():
    projection = project_schedule_rob(
        starting_rob(ulsfo=100),
        consumption_result([consumption_row(1, ulsfo=None), consumption_row(2, ulsfo=10)]),
    )

    assert projection.rows[0].projected_rob_mt["ULSFO"] is None
    assert projection.rows[1].projected_rob_mt["ULSFO"] is None


def test_starting_rob_persistence_saves_and_loads_complete_profile(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    vessel = VesselRepository(database).save_active("Maersk Labrea", "1234567")
    service = ROBService(ROBRepository(database))

    service.save_starting_rob(service.build_starting_rob(vessel.id, {"ULSFO": 100, "VLSFO": 200, "MDO": 50}))
    loaded = service.load_starting_rob(vessel.id)

    assert loaded.quantity_for("ULSFO") == 100
    assert loaded.quantity_for("VLSFO") == 200
    assert loaded.quantity_for("MDO") == 50
