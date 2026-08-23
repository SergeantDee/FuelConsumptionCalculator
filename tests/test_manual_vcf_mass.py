from math import inf, nan

import pytest

from fuel_consumption_calculator.calculations.manual_vcf_mass import ManualVcfMassError, calculate_manual_vcf_mass


def test_calculates_manual_vcf_standard_volume_and_mass():
    result = calculate_manual_vcf_mass(160.0, 0.985, 950.0)
    assert result.standard_volume_15_m3 == pytest.approx(157.6)
    assert result.mass_mt == pytest.approx(149.72)


def test_zero_observed_volume_is_valid():
    assert calculate_manual_vcf_mass(0, 0.985, 950).mass_mt == 0


@pytest.mark.parametrize("observed, vcf, density", [(-1, 1, 1), (1, 0, 1), (1, -1, 1), (1, 1, 0), (1, 1, -1)])
def test_rejects_invalid_ranges(observed, vcf, density):
    with pytest.raises(ManualVcfMassError):
        calculate_manual_vcf_mass(observed, vcf, density)


@pytest.mark.parametrize("observed, vcf, density", [(nan, 1, 1), (1, nan, 1), (1, 1, nan), (inf, 1, 1), (1, -inf, 1), (1, 1, inf)])
def test_rejects_non_finite_values(observed, vcf, density):
    with pytest.raises(ManualVcfMassError, match="finite"):
        calculate_manual_vcf_mass(observed, vcf, density)


def test_does_not_round_internally():
    result = calculate_manual_vcf_mass(1.23456789, 0.987654321, 987.654321)
    assert result.standard_volume_15_m3 == 1.23456789 * 0.987654321
    assert result.mass_mt == result.standard_volume_15_m3 * 987.654321 / 1000
