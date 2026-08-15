from __future__ import annotations

from dataclasses import dataclass


EXCEL_SPEED_RPM_FACTOR = 0.3221598
EXCEL_POWER_COEFFICIENT = 0.0967741935483871
EXCEL_MCR_POWER_KW = 38880.0

DEFAULT_ME_SFOC_POINTS: tuple[tuple[float, float], ...] = (
    (0.0, 225.0),
    (5.0, 205.0),
    (10.0, 195.34),
    (15.0, 191.34),
    (20.0, 189.92),
    (25.0, 189.31),
    (30.0, 188.96),
    (35.0, 188.65),
    (40.0, 188.30),
    (45.0, 187.87),
    (50.0, 187.00),
    (55.0, 186.40),
    (60.0, 185.90),
    (65.0, 185.40),
    (70.0, 185.00),
    (95.0, 184.47),
    (100.0, 184.80),
)


@dataclass(frozen=True, slots=True)
class MainEnginePerformanceResult:
    speed_knots: float
    slip_percent: float
    rpm: float
    power_kw: float
    load_percent: float
    sfoc_g_per_kwh: float
    fuel_mt_per_hour: float
    mode: str = "DETAILED_SFOC"


def reefer_kw_per_unit(ambient_c: float) -> float:
    if ambient_c <= 20.0:
        return 2.0
    if ambient_c >= 38.0:
        return 3.5
    return 2.0 + (ambient_c - 20.0) * 1.5 / 18.0


def fuel_mt_per_hour(power_kw: float, sfoc_g_per_kwh: float) -> float:
    return max(0.0, power_kw) * max(0.0, sfoc_g_per_kwh) / 1_000_000


def rpm_from_speed(speed_knots: float, slip_percent: float, speed_rpm_factor: float = EXCEL_SPEED_RPM_FACTOR) -> float:
    denominator = speed_rpm_factor * (1 - slip_percent / 100)
    if denominator <= 0:
        raise ValueError("Slip/speed factor combination makes RPM impossible.")
    return speed_knots / denominator


def power_from_rpm(rpm: float, power_coefficient: float = EXCEL_POWER_COEFFICIENT) -> float:
    return rpm * rpm * rpm * power_coefficient


def load_percent_from_power(power_kw: float, mcr_power_kw: float = EXCEL_MCR_POWER_KW) -> float:
    if mcr_power_kw <= 0:
        raise ValueError("MCR power must be greater than zero.")
    return power_kw / mcr_power_kw * 100


def interpolate_sfoc(load_percent: float, points: list[tuple[float, float]] | tuple[tuple[float, float], ...]) -> float | None:
    ordered = sorted(points)
    if not ordered:
        return None
    if load_percent < ordered[0][0] or load_percent > ordered[-1][0]:
        return None
    for load, sfoc in ordered:
        if abs(load_percent - load) < 0.000001:
            return sfoc
    for (left_load, left_sfoc), (right_load, right_sfoc) in zip(ordered, ordered[1:]):
        if left_load <= load_percent <= right_load:
            span = right_load - left_load
            ratio = (load_percent - left_load) / span if span else 0.0
            return left_sfoc + ratio * (right_sfoc - left_sfoc)
    return None


def calculate_main_engine_performance(
    speed_knots: float,
    *,
    slip_percent: float = 10.0,
    speed_rpm_factor: float = EXCEL_SPEED_RPM_FACTOR,
    power_coefficient: float = EXCEL_POWER_COEFFICIENT,
    mcr_power_kw: float = EXCEL_MCR_POWER_KW,
    sfoc_points: list[tuple[float, float]] | tuple[tuple[float, float], ...] = DEFAULT_ME_SFOC_POINTS,
    sfoc_override_g_per_kwh: float | None = None,
) -> MainEnginePerformanceResult | None:
    if speed_knots <= 0:
        return None
    rpm = rpm_from_speed(speed_knots, slip_percent, speed_rpm_factor)
    power_kw = power_from_rpm(rpm, power_coefficient)
    load_percent = load_percent_from_power(power_kw, mcr_power_kw)
    sfoc = sfoc_override_g_per_kwh if sfoc_override_g_per_kwh is not None else interpolate_sfoc(load_percent, sfoc_points)
    if sfoc is None:
        return None
    return MainEnginePerformanceResult(
        speed_knots=speed_knots,
        slip_percent=slip_percent,
        rpm=rpm,
        power_kw=power_kw,
        load_percent=load_percent,
        sfoc_g_per_kwh=sfoc,
        fuel_mt_per_hour=fuel_mt_per_hour(power_kw, sfoc),
    )
