from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


class ManualVcfMassError(ValueError):
    """Raised when manual VCF mass inputs are not physically valid."""


@dataclass(frozen=True, slots=True)
class ManualVcfMassResult:
    standard_volume_15_m3: float
    mass_mt: float


def calculate_manual_vcf_mass(
    observed_volume_m3: object,
    manual_vcf: object,
    density_15_kg_m3: object,
) -> ManualVcfMassResult:
    """Calculate standard volume and mass using an operator-provided VCF.

    This is a manual correction only; it does not implement an ASTM/API/ISO VCF.
    """
    observed_volume = _finite(observed_volume_m3, "Observed volume")
    vcf = _finite(manual_vcf, "Manual VCF")
    density = _finite(density_15_kg_m3, "Density at 15°C")
    if observed_volume < 0:
        raise ManualVcfMassError("Observed volume must be at least 0.")
    if vcf <= 0:
        raise ManualVcfMassError("Manual VCF must be greater than 0.")
    if density <= 0:
        raise ManualVcfMassError("Density at 15°C must be greater than 0.")
    standard_volume = observed_volume * vcf
    return ManualVcfMassResult(standard_volume, standard_volume * density / 1000)


def _finite(value: object, label: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as error:
        raise ManualVcfMassError(f"{label} must be numeric.") from error
    if not isfinite(numeric):
        raise ManualVcfMassError(f"{label} must be finite.")
    return numeric
