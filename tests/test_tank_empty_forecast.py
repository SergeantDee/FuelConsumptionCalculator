from datetime import datetime, timedelta, timezone

from fuel_consumption_calculator.calculations.tank_depletion_engine import estimate_tank_empty_time
from fuel_consumption_calculator.domain.tank_forecast import FuelDepletionInterval, TankConsumptionAllocationEvent


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_empty_crossing_is_interpolated_inside_interval():
    interval = FuelDepletionInterval(START, START + timedelta(hours=10), {"ULSFO": 0.0, "VLSFO": 20.0, "MDO": 0.0})
    empty, state, issue = estimate_tank_empty_time(1, "VLSFO", 10.0, START, [interval], [TankConsumptionAllocationEvent(None, 1, START, (1,))], {1: "VLSFO"})
    assert empty == START + timedelta(hours=5)
    assert state == "ESTIMATED" and issue is None


def test_zero_consumption_and_beyond_plan_do_not_invent_time():
    interval = FuelDepletionInterval(START, START + timedelta(hours=10), {"ULSFO": 0.0, "VLSFO": 0.0, "MDO": 0.0})
    empty, state, issue = estimate_tank_empty_time(1, "VLSFO", 10.0, START, [interval], [TankConsumptionAllocationEvent(None, 1, START, (1,))], {1: "VLSFO"})
    assert empty is None and state == "BEYOND_PLAN" and issue == "Beyond current voyage plan"


def test_selection_change_changes_depletion_at_effective_time():
    interval = FuelDepletionInterval(START, START + timedelta(hours=10), {"ULSFO": 0.0, "VLSFO": 20.0, "MDO": 0.0})
    events = [TankConsumptionAllocationEvent(None, 1, START, (1, 2)), TankConsumptionAllocationEvent(None, 1, START + timedelta(hours=5), (2,))]
    empty, state, _ = estimate_tank_empty_time(1, "VLSFO", 5.0, START, [interval], events, {1: "VLSFO", 2: "VLSFO"})
    assert empty == START + timedelta(hours=5) and state == "ESTIMATED"
