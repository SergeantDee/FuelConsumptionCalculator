"""API MPMS Ch. 11.1 / ASTM D1250-style temperature-only CTL at 15 °C.

The application uses the generalized refined-product fuel-oil/diesel group
(API Table 54B metric constants) for VLSFO, ULSFO, and MDO.  Pressure is the
standard atmospheric basis, so VCF here is CTL only.
"""
from __future__ import annotations

from math import exp, isfinite


class AutomaticVcfError(ValueError):
    pass


# API MPMS 11.1 Table 54B metric fuel-oil/diesel referral constants.
_FUEL_OIL_DIESEL = (186.9696, 0.4862, 0.0)
_SUPPORTED_FUELS = frozenset({"VLSFO", "ULSFO", "MDO"})


def calculate_automatic_vcf(density_15_kg_m3: object, observed_temperature_c: object, fuel_type: str | None) -> float:
    """Return the unrounded CTL/VCF to the 15 °C reference basis."""
    if fuel_type not in _SUPPORTED_FUELS:
        raise AutomaticVcfError("Incoming fuel type required for automatic VCF.")
    density = _finite(density_15_kg_m3, "Incoming density at 15°C")
    temperature = _finite(observed_temperature_c, "Incoming bunker temperature")
    if not 611.16 <= density <= 1163.86:
        raise AutomaticVcfError("Incoming density at 15°C is outside the API MPMS 11.1 refined-product range.")
    if not -50 <= temperature <= 150:
        raise AutomaticVcfError("Incoming bunker temperature is outside the API MPMS 11.1 range.")
    k0, k1, k2 = _FUEL_OIL_DIESEL
    alpha_15 = k0 / density ** 2 + k1 / density + k2
    delta_t = temperature - 15.0
    return exp(-alpha_15 * delta_t * (1.0 + 0.8 * alpha_15 * delta_t))


def _finite(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise AutomaticVcfError(f"{label} required.") from error
    if not isfinite(number):
        raise AutomaticVcfError(f"{label} must be finite.")
    return number
