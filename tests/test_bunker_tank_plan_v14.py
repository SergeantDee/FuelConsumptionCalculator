import pytest

from fuel_consumption_calculator.domain.bunker import BunkerReceivingTankPlan
from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, TankSounding
from fuel_consumption_calculator.repositories.bunker_repository import BunkerRepository
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.services.bunker_service import BunkerService
from fuel_consumption_calculator.domain.schedule import ScheduleEvent


@pytest.fixture
def setup(tmp_path):
    db = Database(tmp_path / "v14.db"); db.initialize()
    with db.connect() as c: c.execute("INSERT INTO vessels VALUES (1,'V','1234567','x','x')")
    tanks = FuelTankRepository(db); service = BunkerService(BunkerRepository(db))
    eligible = tanks.save_tank(FuelTank(None, 1, "Eligible", "BUNKER", 500, "SOUNDING", True))
    for name, typ, eligible_flag, active in (("Sett", "SETTLING", True, True), ("Service", "SERVICE", True, True), ("Other", "OTHER", True, True), ("No", "BUNKER", False, True), ("Inactive", "BUNKER", True, False)):
        tanks.save_tank(FuelTank(None, 1, name, typ, 100, "SOUNDING", eligible_flag, active))
    event = ScheduleEvent(id=1, vessel_id=1, sequence_number=1, port="SG", terminal=None, event_type="PORT", arrival_at=__import__('datetime').datetime(2026,1,1), departure_at=None, source="x", source_vessel_name="x", source_from_date=None, created_at="x", updated_at="x")
    plan = service.build_plan(vessel_id=1, event=event, quantities={"ULSFO": 0, "VLSFO": 0, "MDO": 0})
    return db, tanks, service, plan, eligible


def test_eligible_candidates_and_selected_rows_persist(setup):
    _db, tanks, service, plan, eligible = setup
    assert [tank.name for tank, _latest in service.list_eligible_receiving_tanks(1)] == ["Eligible"]
    tanks.save_sounding(TankSounding(None, eligible.id, "2026-01-01T00:00:00+00:00", "SOUNDING", 1, 0, None, 160))
    assert service.list_receiving_tank_plan(plan) == []
    row = BunkerReceivingTankPlan(eligible.id, 160.123, 90.5)
    batch = tanks.save_fuel_batch(FuelBatch(None, 1, "Incoming", "VLSFO", 978))
    service.save_receiving_tank_plan(plan, [row], batch.id, 0.985)
    assert service.list_receiving_tank_plan(plan) == [row]
    snapshot = service.load_incoming_fuel_snapshot(plan)
    assert (snapshot.fuel_batch_id, snapshot.density_15_kg_m3, snapshot.manual_vcf) == (batch.id, 978, 0.985)
    result = service.tank_based_max_lift(plan)
    assert result.total_available_volume_m3 == pytest.approx(292.377)
    assert result.total_max_lift_mt == pytest.approx(292.377 * .985 * 978 / 1000)
    tanks.save_fuel_batch(FuelBatch(batch.id, 1, "Incoming", "VLSFO", 980))
    assert service.tank_based_max_lift(plan).total_max_lift_mt == pytest.approx(292.377 * .985 * 978 / 1000)
    service.save_receiving_tank_plan(plan, [BunkerReceivingTankPlan(eligible.id, None, 90)], batch.id, None)
    assert service.tank_based_max_lift(plan) is None


def test_duplicate_and_ineligible_rows_rejected_and_clear_removes_snapshot(setup):
    _db, _tanks, service, plan, eligible = setup
    row = BunkerReceivingTankPlan(eligible.id, 0, 90)
    with pytest.raises(ValueError, match="only be selected once"):
        service.save_receiving_tank_plan(plan, [row, row], None, None)
    with pytest.raises(ValueError, match="eligible"):
        service.save_receiving_tank_plan(plan, [BunkerReceivingTankPlan(999, 0, 90)], None, None)
    service.save_receiving_tank_plan(plan, [row], None, None)
    service.clear_receiving_tank_plan(plan)
    assert service.list_receiving_tank_plan(plan) == []
    assert service.load_incoming_fuel_snapshot(plan).density_15_kg_m3 is None
