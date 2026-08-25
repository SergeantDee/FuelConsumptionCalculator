from __future__ import annotations

from datetime import datetime, timezone

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.voyage import FuelChangeoverEvent, MachineryFuelState, VesselEnergyConfig
from fuel_consumption_calculator.domain.voyage_stages import OperationalStage, STAGE_PORT_STAY, STAGE_SEA_PASSAGE


def estimate_current_rob(
    *,
    anchor_quantities_mt: dict[str, float | None],
    anchor_at_utc: datetime,
    current_utc: datetime,
    stages: list[OperationalStage],
    initial_fuel_state: MachineryFuelState | None,
    fuel_changeovers: tuple[FuelChangeoverEvent, ...],
    energy_config: VesselEnergyConfig | None = None,
) -> dict[str, float | None]:
    """Consume only elapsed calculated stage quantities from an Actual ROB anchor."""
    result = {fuel: anchor_quantities_mt.get(fuel) for fuel in FUEL_TYPES}
    start = _utc(anchor_at_utc)
    end = _utc(current_utc)
    if end <= start:
        return result
    cursor = start
    for stage in sorted(stages, key=lambda item: _utc(item.start_utc) if item.start_utc else datetime.max.replace(tzinfo=timezone.utc)):
        stage_start = _utc(stage.start_utc) if stage.start_utc else None
        stage_end = _utc(stage.end_utc) if stage.end_utc else None
        if stage_end is not None and stage_end <= start:
            continue
        if stage_start is None or stage_end is None or stage_end <= stage_start:
            return _unknown()
        if stage_start > cursor:
            return _unknown()
        interval_start = max(start, stage_start)
        interval_end = min(end, stage_end)
        if interval_end <= interval_start:
            continue
        rates = _machinery_rates(stage, energy_config)
        if rates is None:
            return _unknown()
        for machinery, rate in rates.items():
            if rate is None:
                return _unknown()
            if rate == 0:
                continue
            if initial_fuel_state is None or not _consume_interval(
                result,
                machinery,
                float(rate),
                interval_start,
                interval_end,
                initial_fuel_state,
                fuel_changeovers,
            ):
                return _unknown()
        cursor = max(cursor, interval_end)
        if cursor >= end:
            break
    if cursor < end:
        return _unknown()
    return result


def _machinery_rates(stage: OperationalStage, energy_config: VesselEnergyConfig | None) -> dict[str, float | None] | None:
    if stage.start_utc is None or stage.end_utc is None:
        return None
    hours = (_utc(stage.end_utc) - _utc(stage.start_utc)).total_seconds() / 3600
    if hours <= 0:
        return None
    if stage.stage_type == STAGE_PORT_STAY:
        if stage.port_breakdown is None:
            return None
        return {
            "MAIN_ENGINE": 0.0,
            "GENERATORS": _divide(_sum(_total(stage.port_breakdown.generator_consumed_mt), _total(stage.port_breakdown.auxiliary_engine_operational_loss_mt)), hours),
            "AUX_BOILER": _divide(_total(stage.port_breakdown.boiler_consumed_mt), hours),
        }
    if stage.stage_type == STAGE_SEA_PASSAGE:
        if stage.leg is None:
            return None
        generators = _total(stage.leg.sea_generator_consumed_mt)
        boiler = _total(stage.leg.sea_boiler_consumed_mt)
        main_engine_loss = _total(stage.leg.sea_main_engine_loss_mt)
        auxiliary_engine_loss = _total(stage.leg.sea_auxiliary_engine_loss_mt)
        total = _total(stage.consumption_mt)
        if generators is None or boiler is None or main_engine_loss is None or auxiliary_engine_loss is None or total is None:
            return None
        return {
            "MAIN_ENGINE": (total - generators - boiler - auxiliary_engine_loss) / hours,
            "GENERATORS": (generators + auxiliary_engine_loss) / hours,
            "AUX_BOILER": boiler / hours,
        }
    if energy_config is None:
        return None
    return {
        "MAIN_ENGINE": _sum(energy_config.maneuvering_main_engine_mt_per_hour, energy_config.main_engine_loss_allowance_mt_per_day / 24),
        "GENERATORS": _sum(
            energy_config.maneuvering_generators_mt_per_hour,
            energy_config.auxiliary_engine_loss_allowance_mt_per_day / 24 if energy_config.maneuvering_generators_mt_per_hour and energy_config.maneuvering_generators_mt_per_hour > 0 else 0.0,
        ),
        "AUX_BOILER": energy_config.maneuvering_aux_boiler_mt_per_hour,
    }


def _consume_interval(result, machinery, rate_mt_per_hour, start, end, initial_fuel_state, changeovers) -> bool:
    fuel = initial_fuel_state.fuel_for(machinery)
    relevant = sorted((event for event in changeovers if event.machinery == machinery), key=lambda event: _utc(event.effective_at_utc))
    for event in relevant:
        if _utc(event.effective_at_utc) <= start:
            fuel = event.to_fuel_type
    if fuel not in FUEL_TYPES:
        return False
    cursor = start
    for event in relevant:
        event_time = _utc(event.effective_at_utc)
        if not (cursor < event_time < end):
            continue
        _deduct(result, fuel, rate_mt_per_hour * (event_time - cursor).total_seconds() / 3600)
        fuel = event.to_fuel_type
        if fuel not in FUEL_TYPES:
            return False
        cursor = event_time
    _deduct(result, fuel, rate_mt_per_hour * (end - cursor).total_seconds() / 3600)
    return True


def _deduct(result: dict[str, float | None], fuel: str, amount: float) -> None:
    if result.get(fuel) is None:
        return
    result[fuel] = float(result[fuel]) - amount


def _total(values: dict[str, float | None] | None) -> float | None:
    if values is None or any(values.get(fuel) is None for fuel in FUEL_TYPES):
        return None
    return sum(float(values.get(fuel) or 0.0) for fuel in FUEL_TYPES)


def _divide(value: float | None, hours: float) -> float | None:
    return None if value is None else value / hours


def _sum(*values: float | None) -> float | None:
    return None if any(value is None for value in values) else sum(float(value) for value in values)


def _unknown() -> dict[str, None]:
    return {fuel: None for fuel in FUEL_TYPES}


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
