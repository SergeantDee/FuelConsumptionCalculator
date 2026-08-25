from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from math import isclose, isfinite

from fuel_consumption_calculator.calculations.manual_vcf_mass import (
    ManualVcfMassError,
    ManualVcfMassResult,
    calculate_manual_vcf_mass as calculate_pure_manual_vcf_mass,
)
from fuel_consumption_calculator.calculations.tank_calibration_engine import calculate_calibrated_volume_m3
from fuel_consumption_calculator.calculations.tank_depletion_engine import allocate_tank_depletion
from fuel_consumption_calculator.domain.fuel_tank import (
    FUEL_BATCH_TYPES,
    FUEL_TANK_TYPES,
    MEASUREMENT_TYPES,
    FuelBatch,
    FuelTank,
    TankCalibrationPoint,
    TankSounding,
)
from fuel_consumption_calculator.domain.tank_forecast import FuelDepletionInterval, TankConsumptionAllocationEvent, TankForecast
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository


class FuelTankValidationError(ValueError):
    pass


class FuelTankService:
    def __init__(self, repository: FuelTankRepository) -> None:
        self._repository = repository

    def list_tanks(self, vessel_id: int, *, include_inactive: bool = False) -> list[FuelTank]:
        return self._repository.list_tanks(vessel_id, include_inactive=include_inactive)

    def get_tank(self, tank_id: int) -> FuelTank | None:
        return self._repository.get_tank(tank_id)

    def create_tank(self, tank: FuelTank) -> FuelTank:
        if tank.id is not None:
            raise FuelTankValidationError("New fuel tanks must not already have an id.")
        return self.save_tank(tank)


    def update_tank(self, tank: FuelTank) -> FuelTank:
        existing = self._repository.get_tank(tank.id) if tank.id is not None else None
        if existing is None:
            raise FuelTankValidationError("Fuel tank does not exist.")
        if tank.vessel_id != existing.vessel_id:
            raise FuelTankValidationError("Fuel tank vessel ownership cannot be changed.")
        return self.save_tank(tank)

    def save_tank(self, tank: FuelTank) -> FuelTank:
        self._validate_tank(tank)
        self._validate_batch_belongs_to_vessel(tank.vessel_id, tank.current_fuel_batch_id)
        return self._repository.save_tank(tank)

    def set_tank_active(self, tank_id: int, is_active: bool) -> FuelTank:
        tank = self._repository.set_tank_active(tank_id, is_active)
        if tank is None:
            raise FuelTankValidationError("Fuel tank does not exist.")
        return tank

    def assign_current_fuel_batch(self, tank_id: int, batch_id: int | None) -> FuelTank:
        tank = self.get_tank(tank_id)
        if tank is None:
            raise FuelTankValidationError("Fuel tank does not exist.")
        self._validate_batch_belongs_to_vessel(tank.vessel_id, batch_id)
        saved = self._repository.assign_current_fuel_batch(tank_id, batch_id)
        if saved is None:
            raise RuntimeError("Fuel tank could not be read after assigning its batch.")
        return saved

    def assign_fuel_batch_to_tank(self, tank_id: int, fuel_batch_id: int) -> FuelTank:
        return self.assign_current_fuel_batch(tank_id, fuel_batch_id)

    def clear_fuel_batch_from_tank(self, tank_id: int) -> FuelTank:
        return self.assign_current_fuel_batch(tank_id, None)

    def list_fuel_batches(self, vessel_id: int) -> list[FuelBatch]:
        return self._repository.list_fuel_batches(vessel_id)

    def get_fuel_batch(self, batch_id: int) -> FuelBatch | None:
        return self._repository.get_fuel_batch(batch_id)

    def create_fuel_batch(self, batch: FuelBatch) -> FuelBatch:
        if batch.id is not None:
            raise FuelTankValidationError("New fuel batches must not already have an id.")
        return self.save_fuel_batch(batch)

    def update_fuel_batch(self, batch: FuelBatch) -> FuelBatch:
        existing = self._repository.get_fuel_batch(batch.id) if batch.id is not None else None
        if existing is None:
            raise FuelTankValidationError("Fuel batch does not exist.")
        if batch.vessel_id != existing.vessel_id:
            raise FuelTankValidationError("Fuel batch vessel ownership cannot be changed.")
        return self.save_fuel_batch(batch)

    def save_fuel_batch(self, batch: FuelBatch) -> FuelBatch:
        batch = replace(batch, batch_name=batch.batch_name.strip())
        self._validate_batch(batch)
        if not self._repository.vessel_exists(batch.vessel_id):
            raise FuelTankValidationError("Fuel batch vessel does not exist.")
        return self._repository.save_fuel_batch(batch)

    def list_calibration_points(self, tank_id: int) -> list[TankCalibrationPoint]:
        return self._repository.list_calibration_points(tank_id)

    def replace_calibration_points(self, tank_id: int, points: list[TankCalibrationPoint]) -> list[TankCalibrationPoint]:
        if self.get_tank(tank_id) is None:
            raise FuelTankValidationError("Fuel tank does not exist.")
        self._validate_calibration_points(tank_id, points)
        return self._repository.replace_calibration_points(tank_id, points)

    def calculate_calibrated_volume(self, tank_id: int, reading_type: str, reading_cm: float, trim_m: float) -> float:
        if self.get_tank(tank_id) is None:
            raise FuelTankValidationError("Fuel tank does not exist.")
        try:
            return calculate_calibrated_volume_m3(self.list_calibration_points(tank_id), reading_type, reading_cm, trim_m)
        except ValueError as error:
            raise FuelTankValidationError(str(error)) from error

    def calculate_manual_vcf_mass(
        self,
        observed_volume_m3: float,
        manual_vcf: float,
        density_15_kg_m3: float,
    ) -> ManualVcfMassResult:
        try:
            return calculate_pure_manual_vcf_mass(
                observed_volume_m3, manual_vcf, density_15_kg_m3
            )
        except ManualVcfMassError as error:
            raise FuelTankValidationError(str(error)) from error

    def save_sounding_observation(
        self, *, tank_id: int, reading_type: str, reading_cm: float, trim_m: float,
        effective_at_utc: datetime | str | None = None, temperature_c: float | None = None,
        fuel_batch_id: int | None = None, remarks: str | None = None,
        manual_vcf: float | None = None, standard_volume_15_m3: float | None = None,
        calculated_density_kg_m3: float | None = None, calculated_mass_mt: float | None = None,
    ) -> TankSounding:
        tank = self.get_tank(tank_id)
        if tank is None:
            raise FuelTankValidationError("Fuel tank does not exist.")
        if reading_type not in MEASUREMENT_TYPES:
            raise FuelTankValidationError("Reading type must be SOUNDING or ULLAGE.")
        self._validate_number(reading_cm, "Reading", minimum=0)
        self._validate_number(trim_m, "Trim")
        if temperature_c is not None:
            self._validate_number(temperature_c, "Temperature")
        self._validate_batch_belongs_to_vessel(tank.vessel_id, fuel_batch_id)
        volume = self.calculate_calibrated_volume(tank_id, reading_type, reading_cm, trim_m)
        self._validate_mass_snapshot(
            calculated_volume_m3=volume,
            manual_vcf=manual_vcf,
            standard_volume_15_m3=standard_volume_15_m3,
            calculated_density_kg_m3=calculated_density_kg_m3,
            calculated_mass_mt=calculated_mass_mt,
        )
        return self._repository.save_sounding(TankSounding(
            id=None, tank_id=tank_id, effective_at_utc=_utc_timestamp(effective_at_utc), reading_type=reading_type,
            reading_cm=float(reading_cm), trim_m=float(trim_m), temperature_c=float(temperature_c) if temperature_c is not None else None,
            calculated_volume_m3=volume,
            calculated_density_kg_m3=(float(calculated_density_kg_m3)
                                        if calculated_density_kg_m3 is not None else None),
            calculated_mass_mt=(float(calculated_mass_mt)
                                if calculated_mass_mt is not None else None),
            fuel_batch_id=fuel_batch_id, remarks=remarks,
            manual_vcf=float(manual_vcf) if manual_vcf is not None else None,
            standard_volume_15_m3=(float(standard_volume_15_m3)
                                    if standard_volume_15_m3 is not None else None),
        ))

    def get_latest_sounding(self, tank_id: int) -> TankSounding | None:
        return self._repository.get_latest_sounding(tank_id)

    def list_sounding_history(self, tank_id: int) -> list[TankSounding]:
        return self._repository.list_sounding_history(tank_id)

    def get_current_tank_state(self, tank_id: int) -> tuple[FuelTank, TankSounding | None]:
        tank = self.get_tank(tank_id)
        if tank is None:
            raise FuelTankValidationError("Fuel tank does not exist.")
        return tank, self.get_latest_sounding(tank_id)

    def list_consumption_allocation_events(self, vessel_id: int) -> list[TankConsumptionAllocationEvent]:
        return self._repository.list_consumption_allocation_events(vessel_id)

    def apply_consumption_tanks(
        self, vessel_id: int, tank_ids: list[int] | tuple[int, ...], effective_at_utc: datetime | None = None,
    ) -> TankConsumptionAllocationEvent:
        selected = tuple(sorted(set(tank_ids)))
        tanks = {tank.id: tank for tank in self.list_tanks(vessel_id, include_inactive=True)}
        for tank_id in selected:
            tank = tanks.get(tank_id)
            if tank is None or tank.tank_type != "BUNKER" or not tank.is_active:
                raise FuelTankValidationError("Only active bunker/storage tanks may be selected for consumption.")
        effective = effective_at_utc or datetime.now(timezone.utc)
        if effective.tzinfo is None:
            effective = effective.replace(tzinfo=timezone.utc)
        return self._repository.save_consumption_allocation_event(
            TankConsumptionAllocationEvent(None, vessel_id, effective, selected)
        )

    def predict_tank_rob_at(
        self, vessel_id: int, target_utc: datetime, intervals: list[FuelDepletionInterval],
    ) -> list[TankForecast]:
        if target_utc.tzinfo is None:
            target_utc = target_utc.replace(tzinfo=timezone.utc)
        tanks = self.list_tanks(vessel_id)
        batches = {batch.id: batch for batch in self.list_fuel_batches(vessel_id)}
        tank_fuels = {tank.id: (batches[tank.current_fuel_batch_id].fuel_type if tank.current_fuel_batch_id in batches else None) for tank in tanks}
        events = self.list_consumption_allocation_events(vessel_id)
        forecasts: list[TankForecast] = []
        for tank in tanks:
            anchor = self._repository.get_latest_sounding_at_or_before(tank.id, target_utc.astimezone(timezone.utc).isoformat(timespec="seconds"))
            fuel = tank_fuels[tank.id]
            if anchor is None:
                forecasts.append(TankForecast(tank.id, fuel, None, None, None, None, "No actual tank sounding available."))
                continue
            if anchor.calculated_mass_mt is None:
                forecasts.append(TankForecast(tank.id, fuel, _parse_utc(anchor.effective_at_utc), None, None, None, "Latest actual tank sounding has no mass snapshot."))
                continue
            if fuel is None:
                forecasts.append(TankForecast(tank.id, None, _parse_utc(anchor.effective_at_utc), anchor.calculated_mass_mt, None, None, "Tank fuel is unknown."))
                continue
            allocations, issues = allocate_tank_depletion(intervals, events, tank_fuels, _parse_utc(anchor.effective_at_utc), target_utc)
            depletion = allocations.get(tank.id)
            issue = issues.get(tank.id)
            forecasts.append(TankForecast(tank.id, fuel, _parse_utc(anchor.effective_at_utc), anchor.calculated_mass_mt, depletion, None if depletion is None else anchor.calculated_mass_mt - depletion, issue))
        return forecasts

    def _validate_tank(self, tank: FuelTank) -> None:
        if tank.vessel_id <= 0:
            raise FuelTankValidationError("Vessel id must be positive.")
        if not " ".join(tank.name.split()):
            raise FuelTankValidationError("Tank name is required.")
        if tank.tank_type not in FUEL_TANK_TYPES:
            raise FuelTankValidationError("Tank type is invalid.")
        if tank.preferred_measurement_type not in MEASUREMENT_TYPES:
            raise FuelTankValidationError("Preferred measurement type must be SOUNDING or ULLAGE.")
        self._validate_number(tank.capacity_m3, "Tank capacity", minimum=0, strictly_positive=True)

    def _validate_batch(self, batch: FuelBatch) -> None:
        if batch.vessel_id <= 0 or not " ".join(batch.batch_name.split()):
            raise FuelTankValidationError("Fuel batch vessel and name are required.")
        if batch.fuel_type not in FUEL_BATCH_TYPES:
            raise FuelTankValidationError("Fuel type is invalid.")
        self._validate_number(batch.density_15_kg_m3, "Density at 15°C", minimum=0, strictly_positive=True)
        if float(batch.density_15_kg_m3) < 100:
            raise FuelTankValidationError(
                "Density must be entered in kg/m³ (for example 978, not 0.978)."
            )
        for label, value in (("Sulfur percent", batch.sulfur_percent), ("Water percent", batch.water_percent)):
            if value is not None:
                self._validate_number(value, label, minimum=0)
        if batch.viscosity_50_cst is not None:
            self._validate_number(
                batch.viscosity_50_cst, "Viscosity", minimum=0, strictly_positive=True
            )
        for label, value in (("Flash point", batch.flash_point_c), ("Pour point", batch.pour_point_c)):
            if value is not None:
                self._validate_number(value, label)

    def _validate_calibration_points(self, tank_id: int, points: list[TankCalibrationPoint]) -> None:
        if not points:
            raise FuelTankValidationError("Calibration table cannot be empty.")
        sounding_axes: set[tuple[float, float]] = set()
        ullage_axes: set[tuple[float, float]] = set()
        for point in points:
            if point.tank_id != tank_id:
                raise FuelTankValidationError("Every calibration point must belong to the selected tank.")
            if point.sounding_cm is None and point.ullage_cm is None:
                raise FuelTankValidationError("Calibration points require a sounding or ullage value.")
            if point.sounding_cm is not None:
                self._validate_number(point.sounding_cm, "Sounding", minimum=0)
                sounding_axis = (point.sounding_cm, point.trim_m)
                if sounding_axis in sounding_axes:
                    raise FuelTankValidationError("Calibration table contains duplicate sounding and trim points.")
                sounding_axes.add(sounding_axis)
            if point.ullage_cm is not None:
                self._validate_number(point.ullage_cm, "Ullage", minimum=0)
                ullage_axis = (point.ullage_cm, point.trim_m)
                if ullage_axis in ullage_axes:
                    raise FuelTankValidationError("Calibration table contains duplicate ullage and trim points.")
                ullage_axes.add(ullage_axis)
            self._validate_number(point.trim_m, "Trim")
            self._validate_number(point.volume_m3, "Calibration volume", minimum=0)

    def _validate_batch_belongs_to_vessel(self, vessel_id: int, batch_id: int | None) -> None:
        if batch_id is not None:
            batch = self.get_fuel_batch(batch_id)
            if batch is None or batch.vessel_id != vessel_id:
                raise FuelTankValidationError("Fuel batch must belong to the tank vessel.")

    def _validate_mass_snapshot(
        self,
        *,
        calculated_volume_m3: float,
        manual_vcf: float | None,
        standard_volume_15_m3: float | None,
        calculated_density_kg_m3: float | None,
        calculated_mass_mt: float | None,
    ) -> None:
        values = (
            manual_vcf,
            standard_volume_15_m3,
            calculated_density_kg_m3,
            calculated_mass_mt,
        )
        if all(value is None for value in values):
            return
        if any(value is None for value in values):
            raise FuelTankValidationError(
                "Mass snapshot requires manual VCF, standard volume, density, and mass."
            )

        self._validate_number(standard_volume_15_m3, "Standard volume at 15 C", minimum=0)
        self._validate_number(calculated_mass_mt, "Calculated mass", minimum=0)
        expected = self.calculate_manual_vcf_mass(
            calculated_volume_m3, manual_vcf, calculated_density_kg_m3
        )
        if not isclose(
            float(standard_volume_15_m3), expected.standard_volume_15_m3,
            rel_tol=1e-9, abs_tol=1e-9,
        ):
            raise FuelTankValidationError(
                "Standard volume does not match the manual VCF snapshot calculation."
            )
        if not isclose(float(calculated_mass_mt), expected.mass_mt, rel_tol=1e-9, abs_tol=1e-9):
            raise FuelTankValidationError(
                "Calculated mass does not match the manual VCF snapshot calculation."
            )

    @staticmethod
    def _validate_number(value: float, label: str, minimum: float | None = None, strictly_positive: bool = False) -> None:
        try:
            numeric = float(value)
        except (TypeError, ValueError) as error:
            raise FuelTankValidationError(f"{label} must be a number.") from error
        if not isfinite(numeric) or (minimum is not None and (numeric <= minimum if strictly_positive else numeric < minimum)):
            comparison = "greater than" if strictly_positive else "at least"
            raise FuelTankValidationError(f"{label} must be {comparison} {minimum}.")


def _utc_timestamp(value: datetime | str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        parsed = value
    if parsed.tzinfo is None:
        raise FuelTankValidationError("Effective timestamp must include a UTC offset.")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
