from math import inf, nan

import pytest

from fuel_consumption_calculator.calculations.tank_max_lift import (
    SelectedReceivingTank,
    TankMaxLiftError,
    calculate_tank_max_lift,
)


def selected(tank_id=1, capacity=500, arrival=160, target=90, **changes):
    values = dict(
        tank_id=tank_id,
        capacity_m3=capacity,
        arrival_volume_m3=arrival,
        target_fill_percent=target,
    )
    values.update(changes)
    return SelectedReceivingTank(**values)


def test_single_and_multiple_selected_tanks_use_individual_target_fills():
    first = selected(1, 500, 160, 90)
    second = selected(2, 600, 400, 95)

    result = calculate_tank_max_lift([first, second])

    assert [(item.tank_id, item.target_volume_m3, item.available_volume_m3) for item in result.tanks] == [
        (1, 450, 290), (2, 570, 170)
    ]
    assert result.total_available_volume_m3 == 460
    assert result.total_max_lift_mt is None


@pytest.mark.parametrize("arrival,target,expected", [(460, 90, 0), (450, 90, 0)])
def test_tank_at_or_above_target_has_zero_available_volume(arrival, target, expected):
    result = calculate_tank_max_lift([selected(arrival=arrival, target=target)])
    assert result.tanks[0].available_volume_m3 == expected


def test_empty_selection_is_valid_and_returns_zero():
    result = calculate_tank_max_lift([])
    assert result.tanks == ()
    assert result.total_available_volume_m3 == 0
    assert result.total_max_lift_mt is None


@pytest.mark.parametrize(
    "changes",
    [
        {"capacity": 0}, {"capacity": -1}, {"arrival": -1},
        {"arrival": 501}, {"arrival": None}, {"target": 0}, {"target": -1},
        {"target": 101}, {"capacity": nan}, {"arrival": inf}, {"target": -inf},
        {"bunker_receiving_eligible": False},
    ],
)
def test_invalid_or_non_eligible_selected_tanks_are_rejected(changes):
    with pytest.raises(TankMaxLiftError):
        calculate_tank_max_lift([selected(**changes)])


def test_incoming_fuel_mt_uses_manual_vcf_and_density_only_when_both_present():
    result = calculate_tank_max_lift(
        [selected()], incoming_density_15_kg_m3=978, incoming_manual_vcf=0.985
    )
    assert result.total_available_volume_m3 == 290
    assert result.total_max_lift_mt == 290 * 0.985 * 978 / 1000
    assert calculate_tank_max_lift([selected()], incoming_density_15_kg_m3=978).total_max_lift_mt is None
    assert calculate_tank_max_lift([selected()], incoming_manual_vcf=0.985).total_max_lift_mt is None


@pytest.mark.parametrize("density,vcf", [(nan, None), (None, inf), (0, None), (None, 0)])
def test_provided_incoming_fuel_values_must_be_valid(density, vcf):
    with pytest.raises(TankMaxLiftError):
        calculate_tank_max_lift([selected()], incoming_density_15_kg_m3=density, incoming_manual_vcf=vcf)


def test_calculation_is_unrounded_and_does_not_mutate_inputs():
    tank = selected(capacity=123.456789, arrival=1.234567, target=98.7654321)
    original = tank

    result = calculate_tank_max_lift([tank])

    assert tank == original
    assert result.tanks[0].target_volume_m3 == 123.456789 * 98.7654321 / 100
    assert result.tanks[0].available_volume_m3 == result.tanks[0].target_volume_m3 - 1.234567
