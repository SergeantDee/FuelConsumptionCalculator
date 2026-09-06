from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from fuel_consumption_calculator.calculations.rob_projection_engine import project_schedule_rob
from fuel_consumption_calculator.calculations.voyage_engine import (
    calculate_voyage_consumption,
    calculate_voyage_plan,
)
from fuel_consumption_calculator.domain.bunker import BunkerReceivingTankPlan, BunkerTankReceipt
from fuel_consumption_calculator.domain.consumption import ConsumptionProfile, ConsumptionRate, FUEL_TYPES
from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, TankCalibrationPoint
from fuel_consumption_calculator.domain.rob import ROBQuantity, StartingROB
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.schedule_timeline import build_schedule_timeline
from fuel_consumption_calculator.domain.tank_forecast import (
    FuelDepletionInterval,
    TankConsumptionPlan,
    TankConsumptionPlanPhase,
    TankConsumptionPlanPhaseTank,
)
from fuel_consumption_calculator.domain.voyage import (
    GeneratorSfocPoint,
    MachineryFuelState,
    RouteDefinition,
    SpeedConsumptionPoint,
    VesselEnergyConfig,
    VoyageLeg,
)
from fuel_consumption_calculator.domain.voyage_stages import build_voyage_stage_timeline
from fuel_consumption_calculator.repositories.bunker_repository import BunkerRepository
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.bunker_service import BunkerService
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService


def test_schedule_to_sounding_reanchor_authority_chain(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    arrival = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    departure = datetime(2026, 1, 3, tzinfo=timezone.utc)
    events = [
        _event(1, "Origin", start - timedelta(hours=12), start),
        _event(2, "Destination", arrival, departure),
    ]
    schedule_timeline = build_schedule_timeline(events)
    voyage_plan = calculate_voyage_plan(
        [
            VoyageLeg(
                1, 2, 1, 2, "Origin", "Destination", start, arrival,
                RouteDefinition("Origin", "Destination", 5, 2, 320, 5, 2),
            )
        ],
        _profile(),
        [SpeedConsumptionPoint(1, 10, {"ULSFO": 0, "VLSFO": 24, "MDO": 0}, 30)],
        _energy_config(),
        [GeneratorSfocPoint(1, 0, 200), GeneratorSfocPoint(1, 100, 200)],
        MachineryFuelState(1, "VLSFO", "ULSFO", "MDO"),
    )
    voyage_result = calculate_voyage_consumption(schedule_timeline, events, voyage_plan, _profile())
    starting_rob = StartingROB(1, tuple(ROBQuantity(fuel, 500) for fuel in FUEL_TYPES))
    aggregate_projection = project_schedule_rob(starting_rob, voyage_result.consumption)
    stage_timeline = build_voyage_stage_timeline(
        events,
        voyage_plan,
        starting_rob,
        port_breakdowns=voyage_result.port_breakdowns,
        now_utc=start - timedelta(days=1),
    )

    assert not schedule_timeline.issues
    assert len(stage_timeline.stages) == 5
    assert aggregate_projection.rows[1].projected_rob_mt["VLSFO"] is not None

    database = Database(tmp_path / "end-to-end.db")
    database.initialize()
    vessel = VesselRepository(database).save_active("Synthetic Vessel", "1234567")
    tank_service = FuelTankService(FuelTankRepository(database))
    batch = tank_service.create_fuel_batch(FuelBatch(None, vessel.id, "VLSFO-TEST", "VLSFO", 978))
    first = _mass_tank(tank_service, vessel.id, batch.id, "HFO DEEP TK 1P", start - timedelta(hours=1), 5 / 0.978)
    second_port = _mass_tank(tank_service, vessel.id, batch.id, "HFO DEEP TK 2P", start - timedelta(hours=1), 5 / 0.978)
    second_starboard = _mass_tank(tank_service, vessel.id, batch.id, "HFO DEEP TK 2S", start - timedelta(hours=1), 5 / 0.978)
    third = _mass_tank(tank_service, vessel.id, batch.id, "HFO DEEP TK 3P", start - timedelta(hours=1), 200 / 0.978)
    tank_service.save_consumption_plan(
        TankConsumptionPlan(
            None,
            vessel.id,
            "VLSFO",
            "ACTIVE",
            start - timedelta(hours=1),
            (
                TankConsumptionPlanPhase(None, 1, (TankConsumptionPlanPhaseTank(first.id, 1.0),)),
                TankConsumptionPlanPhase(None, 2, (
                    TankConsumptionPlanPhaseTank(second_port.id, 0.5),
                    TankConsumptionPlanPhaseTank(second_starboard.id, 0.5),
                )),
                TankConsumptionPlanPhase(None, 3, (TankConsumptionPlanPhaseTank(third.id, 1.0),)),
            ),
        )
    )
    interval = FuelDepletionInterval(
        start - timedelta(hours=1),
        arrival,
        {"VLSFO": voyage_plan.legs[0].total_pre_arrival_consumed_mt["VLSFO"]},
    )
    arrival_forecasts = {
        item.tank_id: item
        for item in tank_service.predict_tank_rob_at(vessel.id, arrival, [interval])
    }

    assert interval.deductions_mt["VLSFO"] > 15
    assert arrival_forecasts[first.id].predicted_mass_mt == pytest.approx(0)
    assert arrival_forecasts[second_port.id].predicted_mass_mt == pytest.approx(0)
    assert arrival_forecasts[second_starboard.id].predicted_mass_mt == pytest.approx(0)
    assert arrival_forecasts[third.id].predicted_mass_mt > 0
    assert arrival_forecasts[third.id].active_phase_sequence == 3
    assert arrival_forecasts[first.id].estimated_depleted_at_utc < arrival_forecasts[second_port.id].estimated_depleted_at_utc
    assert arrival_forecasts[second_port.id].estimated_depleted_at_utc == arrival_forecasts[second_starboard.id].estimated_depleted_at_utc
    assert all(item.predicted_mass_mt is None or item.predicted_mass_mt >= 0 for item in arrival_forecasts.values())
    assert sum(item.predicted_mass_mt or 0 for item in arrival_forecasts.values()) == pytest.approx(
        215 - interval.deductions_mt["VLSFO"]
    )

    class ForecastAdapter:
        def predict_tank_rob_at(self, vessel_id, target_utc):
            return tank_service.predict_tank_rob_at(vessel_id, target_utc, [interval])

        def anchor_sounding_at(self, tank_id, target_utc):
            return tank_service.get_latest_sounding_at_or_before(tank_id, target_utc)

    bunker_service = BunkerService(BunkerRepository(database), ForecastAdapter())
    bunker_plan = bunker_service.build_plan(
        vessel_id=vessel.id,
        event=events[1],
        quantities={"ULSFO": 0, "VLSFO": 50, "MDO": 0},
    )
    bunker_plan = bunker_service.save_plan(bunker_plan) or bunker_plan
    bunker_service.save_receiving_tank_plan(
        bunker_plan,
        [BunkerReceivingTankPlan(first.id, None, 90)],
        batch.id,
        None,
        incoming_temperature_c=15,
        vcf_mode="AUTO",
    )
    arrival_projection = bunker_service.resolve_receiving_tank_arrivals(bunker_plan)[first.id]
    max_lift = bunker_service.tank_based_max_lift(bunker_plan)

    assert arrival_projection.source == "ESTIMATED"
    assert arrival_projection.projected_arrival_volume_m3 == pytest.approx(0)
    assert max_lift is not None and max_lift.total_max_lift_mt > 50

    bunker_plan = bunker_service.confirm_plan(bunker_plan) or bunker_plan
    bunker_service.save_tank_receipts(
        bunker_plan,
        [BunkerTankReceipt(first.id, "VLSFO", 50, "")],
    )
    aggregate_with_bunker = bunker_service.project_schedule_rob_with_bunkers(
        starting_rob=starting_rob,
        consumption=voyage_result.consumption,
        active_bunker_plans=[bunker_plan],
    )
    after_receipt = {
        item.tank_id: item
        for item in tank_service.predict_tank_rob_at(vessel.id, arrival + timedelta(minutes=1), [interval])
    }

    assert aggregate_with_bunker.rows[1].post_bunker_rob_mt["VLSFO"] == pytest.approx(
        aggregate_with_bunker.rows[1].arrival_rob_mt["VLSFO"] + 50
    )
    assert sum(item.quantity_mt for item in bunker_service.list_tank_receipts(bunker_plan)) == pytest.approx(50)
    assert after_receipt[first.id].predicted_mass_mt == pytest.approx(50)

    tank_service.save_sounding_observation(
        tank_id=first.id,
        reading_type="SOUNDING",
        reading_cm=50,
        trim_m=0,
        temperature_c=15,
        effective_at_utc=arrival + timedelta(minutes=30),
    )
    reanchored = {
        item.tank_id: item
        for item in tank_service.predict_tank_rob_at(vessel.id, arrival + timedelta(hours=1), [interval])
    }
    assert reanchored[first.id].predicted_mass_mt == pytest.approx(244.5)


def _event(sequence: int, port: str, arrival: datetime, departure: datetime) -> ScheduleEvent:
    return ScheduleEvent(
        sequence,
        1,
        sequence,
        port,
        "Port Call",
        arrival,
        departure,
        "manual",
        "Synthetic Vessel",
        date(2026, 1, 1),
        "",
        "",
        arrival_at_utc=arrival,
        departure_at_utc=departure,
    )


def _profile() -> ConsumptionProfile:
    return ConsumptionProfile(
        1,
        tuple(
            ConsumptionRate(mode, fuel, 0)
            for mode in ("SEA", "MANEUVERING", "PORT")
            for fuel in FUEL_TYPES
        ),
    )


def _energy_config() -> VesselEnergyConfig:
    return VesselEnergyConfig(
        vessel_id=1,
        port_base_load_kw=1500,
        sea_base_load_kw=1000,
        generator_rated_kw=5000,
        port_running_generators=1,
        sea_running_generators=1,
        aux_boiler_mt_per_hour=0.1,
        generator_fuel_type="ULSFO",
        boiler_fuel_type="MDO",
        maneuvering_main_engine_mt_per_hour=1.5,
        maneuvering_generators_mt_per_hour=0.3,
        maneuvering_aux_boiler_mt_per_hour=0.1,
    )


def _mass_tank(service: FuelTankService, vessel_id: int, batch_id: int, name: str, observed_at: datetime, volume_m3: float):
    tank = service.create_tank(FuelTank(None, vessel_id, name, "BUNKER", 500, "SOUNDING", True, current_fuel_batch_id=batch_id))
    service.replace_calibration_points(
        tank.id,
        [
            TankCalibrationPoint(None, tank.id, 0, None, 0, 0),
            TankCalibrationPoint(None, tank.id, 100, None, 0, 500),
        ],
    )
    service.save_sounding_observation(
        tank_id=tank.id,
        reading_type="SOUNDING",
        reading_cm=volume_m3 / 5,
        trim_m=0,
        temperature_c=15,
        effective_at_utc=observed_at,
    )
    return tank
