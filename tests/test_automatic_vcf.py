import pytest

from fuel_consumption_calculator.calculations.automatic_vcf import AutomaticVcfError, calculate_automatic_vcf


@pytest.mark.parametrize(("fuel", "density"), [("MDO", 850.0), ("ULSFO", 1010.0), ("VLSFO", 978.0)])
def test_api_mpms_11_1_temperature_reference_is_unity(fuel, density):
    assert calculate_automatic_vcf(density, 15.0, fuel) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("fuel", "density", "temperature", "expected"),
    [
        ("VLSFO", 978.0, 35.0, 0.986091857495),
        ("VLSFO", 978.0, 5.0, 1.006911527555),
        ("MDO", 850.0, 35.0, 0.983304449272),
        ("ULSFO", 1010.0, 5.0, 1.006633277288),
    ],
)
def test_api_mpms_11_1_table_54b_reference_vectors(fuel, density, temperature, expected):
    assert calculate_automatic_vcf(density, temperature, fuel) == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize(("density", "temperature", "fuel"), [(978, 20, "UNKNOWN"), (600, 20, "VLSFO"), (978, 151, "VLSFO"), (float("nan"), 20, "MDO")])
def test_automatic_vcf_rejects_unsupported_or_invalid_inputs(density, temperature, fuel):
    with pytest.raises(AutomaticVcfError):
        calculate_automatic_vcf(density, temperature, fuel)


def test_automatic_vcf_does_not_round_intermediate_values():
    value = calculate_automatic_vcf(978.123456789, 31.23456789, "VLSFO")
    assert value != round(value, 5)
