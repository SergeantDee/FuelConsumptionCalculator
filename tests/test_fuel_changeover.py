from math import inf, nan

import pytest

from fuel_consumption_calculator.calculations.fuel_changeover import FuelChangeoverCalculationError, calculate_fuel_changeover


def test_verified_lr_reference_progression_and_trace():
    result = calculate_fuel_changeover(.2, 1, 1.2, .1, .5)
    assert result.changeover_time_hours == 5.0
    assert result.steps == 50 and result.changeover_time_hours == result.steps * .1
    assert result.trace[0].time_hours == 0 and result.trace[0].sulfur_percent == 1.2
    assert result.trace[49].sulfur_percent == pytest.approx(.50813, abs=.0001)
    assert result.trace[50].sulfur_percent == pytest.approx(.49995, abs=.0001)
    assert result.trace[-1].sulfur_percent == result.final_sulfur_percent
    assert result.final_sulfur_percent <= .5


@pytest.mark.parametrize("entered,expected", [(.1, .099), (.5, .499), (.08, .08), (.2, .2)])
def test_replacement_offsets_are_calculation_only(entered, expected):
    result = calculate_fuel_changeover(.2, 1, 1.2, entered, .5)
    assert result.entered_replacement_sulfur_percent == entered
    assert result.calculation_replacement_sulfur_percent == expected


def test_increasing_changeover_and_zero_time():
    increasing = calculate_fuel_changeover(.2, 1, .1, 1.2, .5)
    assert increasing.final_sulfur_percent >= .5
    assert calculate_fuel_changeover(.2, 1, .5, .1, .5).changeover_time_hours == 0


@pytest.mark.parametrize("args", [(0,1,1,.1,.5), (.2,.0009,1,.1,.5), (.2,1,-1,.1,.5), (nan,1,1,.1,.5), (inf,1,1,.1,.5), (20,1,1,.1,.5), (.2,1,1,.8,.5), (.2,1,.1,.1,.5)])
def test_invalid_inputs_and_unreachable_targets_are_rejected(args):
    with pytest.raises(FuelChangeoverCalculationError): calculate_fuel_changeover(*args)


def test_no_internal_rounding_and_horizon_limit():
    result = calculate_fuel_changeover(.123456, 1, 1.234567, .2, .5)
    assert result.final_sulfur_percent != round(result.final_sulfur_percent, 3)
    with pytest.raises(FuelChangeoverCalculationError, match="200-hour"):
        calculate_fuel_changeover(.00001, 1, 1.2, .1, .5)
