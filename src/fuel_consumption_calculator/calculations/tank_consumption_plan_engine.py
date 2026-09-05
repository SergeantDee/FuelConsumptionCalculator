"""Chronological, depletion-driven distribution of authoritative deductions."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from fuel_consumption_calculator.domain.tank_forecast import FuelDepletionInterval, TankConsumptionPlan, TankPlanForecast

_EPSILON = 1e-9


def forecast_tank_consumption_plan(
    plan: TankConsumptionPlan, intervals: list[FuelDepletionInterval], tank_masses_mt: dict[int, float | None], target_utc: datetime,
    physical_events: Iterable[tuple[datetime, str, int, float]] = (),
) -> TankPlanForecast:
    """Forecast one fuel plan in UTC order.

    Events are (time, kind, tank_id, mass): transfers, receipts, and mass-bearing
    soundings. A sounding replaces the forecasted mass at that instant (re-anchor).
    Voyage deductions remain the only consumption authority.
    """
    target, cursor = _utc(target_utc), _utc(plan.effective_from_utc)
    masses = dict(tank_masses_mt)
    depleted = {tank_id: None for phase in plan.phases for tank_id in (item.tank_id for item in phase.tanks)}
    starts = {phase.sequence_number: None for phase in plan.phases}
    if target <= cursor or not plan.phases:
        return TankPlanForecast(masses, depleted, starts, None, 0.0, ("No consumption phase configured",) if not plan.phases else ())
    starts[plan.phases[0].sequence_number] = cursor
    issues: list[str] = []; unallocated = 0.0; phase_index = 0
    events = sorted(((_utc(at), kind, tank_id, float(mass)) for at, kind, tank_id, mass in physical_events if cursor < _utc(at) <= target), key=lambda event: (event[0], {"TRANSFER_OUT": 0, "TRANSFER_IN": 1, "RECEIPT": 2, "SOUNDING": 3}.get(event[1], 9), event[2]))
    boundaries = {cursor, target, *(at for at, *_ in events)}
    for interval in intervals: boundaries.update((_utc(interval.start_utc), _utc(interval.end_utc)))
    boundaries = sorted(boundary for boundary in boundaries if cursor <= boundary <= target)
    by_time: dict[datetime, list[tuple[str, int, float]]] = {}
    for at, kind, tank_id, mass in events: by_time.setdefault(at, []).append((kind, tank_id, mass))
    for begin, end in zip(boundaries, boundaries[1:]):
        phase_index = _apply_events_and_transition(plan, masses, depleted, starts, phase_index, begin, by_time.get(begin, ()))
        for interval in sorted(intervals, key=lambda item: _utc(item.start_utc)):
            start, finish = _utc(interval.start_utc), _utc(interval.end_utc)
            if not (start <= begin and end <= finish) or end <= begin: continue
            amount = interval.deductions_mt.get(plan.fuel_type)
            if amount is None: issues.append(f"Authoritative {plan.fuel_type} depletion is unavailable"); continue
            seconds = (finish - start).total_seconds()
            if seconds > 0:
                phase_index, extra = _consume(plan, masses, depleted, starts, phase_index, begin, end, float(amount) / seconds); unallocated += extra
            break
    phase_index = _apply_events_and_transition(plan, masses, depleted, starts, phase_index, target, by_time.get(target, ()))
    if unallocated > _EPSILON: issues.append("UNALLOCATED FUTURE CONSUMPTION")
    return TankPlanForecast(masses, depleted, starts, plan.phases[phase_index].sequence_number if phase_index < len(plan.phases) else None, unallocated, tuple(dict.fromkeys(issues)))


def _consume(plan, masses, depleted, starts, phase_index, begin, end, rate):
    instant, unallocated = begin, 0.0
    while instant < end:
        if phase_index >= len(plan.phases): return phase_index, unallocated + rate * (end - instant).total_seconds()
        phase = plan.phases[phase_index]
        if any(masses.get(item.tank_id) is None for item in phase.tanks): return phase_index, unallocated + rate * (end - instant).total_seconds()
        if rate <= 0: return phase_index, unallocated
        limiting = min(max(0.0, float(masses[item.tank_id]) - phase.depletion_threshold_mt) / (rate * item.allocation_fraction) for item in phase.tanks)
        available = (end - instant).total_seconds(); elapsed = min(available, limiting)
        for item in phase.tanks: masses[item.tank_id] = max(phase.depletion_threshold_mt, float(masses[item.tank_id]) - rate * elapsed * item.allocation_fraction)
        instant = instant + (end - instant) * (elapsed / available) if elapsed else instant
        if limiting <= elapsed + _EPSILON:
            for item in phase.tanks:
                if float(masses[item.tank_id]) <= phase.depletion_threshold_mt + _EPSILON: masses[item.tank_id] = phase.depletion_threshold_mt; depleted[item.tank_id] = instant
            phase_index += 1
            if phase_index < len(plan.phases): starts[plan.phases[phase_index].sequence_number] = instant
            if elapsed <= _EPSILON: continue
        else: break
    return phase_index, unallocated


def _apply_events_and_transition(plan, masses, depleted, starts, phase_index, instant, events):
    for kind, tank_id, mass in events:
        if tank_id not in masses: continue
        if kind == "SOUNDING": masses[tank_id] = max(0.0, mass)
        elif masses[tank_id] is not None: masses[tank_id] = max(0.0, float(masses[tank_id]) + (-mass if kind == "TRANSFER_OUT" else mass))
    while phase_index < len(plan.phases):
        phase = plan.phases[phase_index]; limiting = [item for item in phase.tanks if masses.get(item.tank_id) is not None and float(masses[item.tank_id]) <= phase.depletion_threshold_mt + _EPSILON]
        if not limiting: break
        for item in limiting: masses[item.tank_id] = phase.depletion_threshold_mt; depleted[item.tank_id] = instant
        phase_index += 1
        if phase_index < len(plan.phases): starts[plan.phases[phase_index].sequence_number] = instant
    return phase_index


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
