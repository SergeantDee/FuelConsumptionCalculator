from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, TankCalibrationPoint
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService, FuelTankValidationError


def test_survey_saves_atomic_common_time_trim_and_vcf_snapshot(tmp_path):
    database = Database(tmp_path / "survey.db"); database.initialize(); VesselRepository(database).save_active("Vessel", "1234567")
    service = FuelTankService(FuelTankRepository(database)); batch = service.create_fuel_batch(FuelBatch(None, 1, "VLSFO", "VLSFO", 950))
    tank = service.create_tank(FuelTank(None, 1, "Tank", "BUNKER", 100, "SOUNDING", current_fuel_batch_id=batch.id))
    service.replace_calibration_points(tank.id, [TankCalibrationPoint(None, tank.id, 0, None, 0, 0), TankCalibrationPoint(None, tank.id, 100, None, 0, 200)])
    at = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    saved = service.save_sounding_survey(1, at, 0, "rounds", [{"include": True, "tank_id": tank.id, "reading_type": "SOUNDING", "reading_cm": "80", "temperature_c": "", "manual_vcf": "0.985"}])
    assert len(saved) == 1
    sounding = saved[0]
    assert sounding.survey_id is not None
    assert sounding.effective_at_utc == at.isoformat(timespec="seconds")
    assert sounding.calculated_volume_m3 == 160
    assert sounding.standard_volume_15_m3 == pytest.approx(157.6)
    assert sounding.calculated_mass_mt == pytest.approx(149.72)


def test_invalid_included_survey_row_saves_nothing(tmp_path):
    database = Database(tmp_path / "survey-invalid.db"); database.initialize(); VesselRepository(database).save_active("Vessel", "1234567")
    service = FuelTankService(FuelTankRepository(database)); tank = service.create_tank(FuelTank(None, 1, "Tank", "BUNKER", 100, "SOUNDING"))
    service.replace_calibration_points(tank.id, [TankCalibrationPoint(None, tank.id, 0, None, 0, 0), TankCalibrationPoint(None, tank.id, 100, None, 0, 200)])
    with pytest.raises(FuelTankValidationError, match="Reading is required"):
        service.save_sounding_survey(1, datetime(2026, 1, 1, tzinfo=timezone.utc), 0, None, [{"include": True, "tank_id": tank.id, "reading_type": "SOUNDING", "reading_cm": "", "temperature_c": "", "manual_vcf": ""}])
    assert service.list_sounding_history(tank.id) == []
