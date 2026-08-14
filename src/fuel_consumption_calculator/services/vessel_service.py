from __future__ import annotations

from fuel_consumption_calculator.domain.vessel import Vessel
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository


class VesselValidationError(ValueError):
    pass


class VesselService:
    def __init__(self, repository: VesselRepository) -> None:
        self._repository = repository

    def get_active_vessel(self) -> Vessel | None:
        return self._repository.get_active()

    def configure_active_vessel(self, name: str, imo: str) -> Vessel:
        clean_name = " ".join(name.split())
        clean_imo = imo.strip().replace(" ", "")
        if not clean_name:
            raise VesselValidationError("Vessel name is required.")
        if not (clean_imo.isdigit() and len(clean_imo) == 7):
            raise VesselValidationError("IMO number must contain exactly 7 digits.")
        return self._repository.save_active(clean_name, clean_imo)
