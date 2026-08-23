from __future__ import annotations

from collections.abc import Iterable
from math import isfinite

from fuel_consumption_calculator.domain.fuel_tank import MEASUREMENT_TYPES, TankCalibrationPoint


class CalibrationError(ValueError):
    """Raised when a calibration table cannot calculate a reliable volume."""


def calculate_calibrated_volume_m3(
    points: Iterable[TankCalibrationPoint],
    reading_type: str,
    reading_cm: float,
    trim_m: float,
) -> float:
    if reading_type not in MEASUREMENT_TYPES:
        raise CalibrationError("Reading type must be SOUNDING or ULLAGE.")
    reading = _finite_float(reading_cm, "Reading")
    trim = _finite_float(trim_m, "Trim")
    if reading < 0:
        raise CalibrationError("Reading cannot be negative.")
    values: dict[tuple[float, float], float] = {}
    for point in points:
        selected_reading = point.sounding_cm if reading_type == "SOUNDING" else point.ullage_cm
        if selected_reading is None:
            continue
        key = (_finite_float(selected_reading, f"{reading_type.title()} calibration reading"), _finite_float(point.trim_m, "Calibration trim"))
        if key in values:
            raise CalibrationError(f"Calibration table contains duplicate {reading_type.lower()} reading and trim points.")
        values[key] = _finite_float(point.volume_m3, "Calibration volume")
    if not values:
        raise CalibrationError(f"No {reading_type.lower()} calibration values are configured for this tank.")
    readings = sorted({value[0] for value in values})
    trims = sorted({value[1] for value in values})
    low_reading, high_reading = _bounds(readings, reading, f"{reading_type.title()} reading")
    low_trim, high_trim = _bounds(trims, trim, "Trim")
    corners = ((low_reading, low_trim), (low_reading, high_trim), (high_reading, low_trim), (high_reading, high_trim))
    missing = [corner for corner in corners if corner not in values]
    if missing:
        raise CalibrationError("Calibration table is missing required interpolation corner(s).")
    q11, q12, q21, q22 = (values[corner] for corner in corners)
    if low_reading == high_reading and low_trim == high_trim:
        return q11
    if low_reading == high_reading:
        return _linear(trim, low_trim, high_trim, q11, q12)
    if low_trim == high_trim:
        return _linear(reading, low_reading, high_reading, q11, q21)
    r1 = _linear(trim, low_trim, high_trim, q11, q12)
    r2 = _linear(trim, low_trim, high_trim, q21, q22)
    return _linear(reading, low_reading, high_reading, r1, r2)


def _bounds(values: list[float], requested: float, label: str) -> tuple[float, float]:
    if requested < values[0] or requested > values[-1]:
        raise CalibrationError(f"{label} is outside the configured calibration range.")
    return max(value for value in values if value <= requested), min(value for value in values if value >= requested)


def _linear(x: float, x1: float, x2: float, y1: float, y2: float) -> float:
    if x1 == x2:
        return y1
    return y1 + ((x - x1) / (x2 - x1)) * (y2 - y1)


def _finite_float(value: object, label: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as error:
        raise CalibrationError(f"{label} must be a number.") from error
    if not isfinite(numeric):
        raise CalibrationError(f"{label} must be finite.")
    return numeric
