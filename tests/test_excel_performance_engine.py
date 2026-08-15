from __future__ import annotations

from fuel_consumption_calculator.calculations.performance_engine import (
    DEFAULT_ME_SFOC_POINTS,
    calculate_main_engine_performance,
    fuel_mt_per_hour,
    interpolate_sfoc,
    reefer_kw_per_unit,
)


def test_excel_parity_speed_rpm_power_load_sfoc_fuel_case():
    result = calculate_main_engine_performance(
        16.355101034993076,
        sfoc_override_g_per_kwh=175.0,
    )

    assert result is not None
    assert round(result.rpm, 6) == round(56.40782767845535, 6)
    assert round(result.power_kw, 6) == round(17369.114802965134, 6)
    assert round(result.load_percent, 6) == round(44.673649184581105, 6)
    assert result.sfoc_g_per_kwh == 175.0
    assert round(result.fuel_mt_per_hour, 6) == round(3.0395950905188984, 6)


def test_me_fuel_mt_per_hour_uses_power_times_sfoc():
    assert fuel_mt_per_hour(17369.114802965134, 175.0) == 3.0395950905188984


def test_main_engine_sfoc_interpolates_from_workbook_points():
    sfoc = interpolate_sfoc(44.673649184581105, DEFAULT_ME_SFOC_POINTS)

    assert sfoc is not None
    assert round(sfoc, 3) == 187.898


def test_reefer_kw_per_unit_at_20c_is_average():
    assert reefer_kw_per_unit(20.0) == 2.0


def test_reefer_kw_per_unit_at_38c_is_maximum():
    assert reefer_kw_per_unit(38.0) == 3.5


def test_reefer_kw_per_unit_midpoint_interpolates():
    assert reefer_kw_per_unit(29.0) == 2.75


def test_generator_fuel_uses_electrical_load_and_sfoc():
    assert fuel_mt_per_hour(1500 + 3.5 * 260, 235.0) == 0.56635
