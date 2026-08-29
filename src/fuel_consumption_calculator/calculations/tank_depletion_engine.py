from __future__ import annotations

from datetime import datetime, timezone

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.fuel_tank import InternalFuelTransfer
from fuel_consumption_calculator.domain.bunker import BunkerTankReceipt
from fuel_consumption_calculator.domain.tank_forecast import FuelDepletionInterval, TankConsumptionAllocationEvent


def transfer_net_mt(
    tank_id: int, transfers: list[InternalFuelTransfer], start_utc: datetime, target_utc: datetime,
) -> float:
    """Return the signed MT movement for one tank; transfers never affect vessel ROB."""
    total = 0.0
    for transfer in transfers:
        effective = _transfer_time(transfer)
        if _utc(start_utc) < effective <= _utc(target_utc):
            if transfer.from_tank_id == tank_id:
                total -= transfer.quantity_mt
            if transfer.to_tank_id == tank_id:
                total += transfer.quantity_mt
    return total


def bunker_receipt_net_mt(tank_id: int, receipts: list[BunkerTankReceipt], start_utc: datetime, target_utc: datetime) -> float:
    return sum(receipt.quantity_mt for receipt in receipts if receipt.tank_id == tank_id and _utc(datetime.fromisoformat(receipt.effective_at_utc)) > _utc(start_utc) and _utc(datetime.fromisoformat(receipt.effective_at_utc)) <= _utc(target_utc))


def allocate_tank_depletion(
    intervals: list[FuelDepletionInterval],
    allocation_events: list[TankConsumptionAllocationEvent],
    tank_fuels: dict[int, str | None],
    start_utc: datetime,
    target_utc: datetime,
) -> tuple[dict[int, float | None], dict[int, str]]:
    """Equally distribute existing per-fuel deductions without changing them."""
    allocations: dict[int, float | None] = {tank_id: 0.0 for tank_id in tank_fuels}
    issues: dict[int, str] = {}
    events = sorted(allocation_events, key=lambda event: _utc(event.effective_at_utc))
    for interval in intervals:
        interval_start, interval_end = max(_utc(interval.start_utc), _utc(start_utc)), min(_utc(interval.end_utc), _utc(target_utc))
        if interval_end <= interval_start:
            continue
        original_start, original_end = _utc(interval.start_utc), _utc(interval.end_utc)
        duration = (original_end - original_start).total_seconds()
        if duration <= 0:
            continue
        boundaries = [interval_start, *(_utc(event.effective_at_utc) for event in events if interval_start < _utc(event.effective_at_utc) < interval_end), interval_end]
        for segment_start, segment_end in zip(boundaries, boundaries[1:]):
            share = (segment_end - segment_start).total_seconds() / duration
            state = _state_at(events, segment_start)
            for fuel in FUEL_TYPES:
                deduction = interval.deductions_mt.get(fuel)
                if deduction is None:
                    for tank_id, tank_fuel in tank_fuels.items():
                        if tank_fuel == fuel:
                            allocations[tank_id] = None
                            issues[tank_id] = f"Authoritative {fuel} depletion is unavailable"
                    continue
                active = [tank_id for tank_id in state if tank_fuels.get(tank_id) == fuel]
                if not active:
                    issues_for_fuel = f"No active {fuel} consumption tank selected"
                    for tank_id, tank_fuel in tank_fuels.items():
                        if tank_fuel == fuel:
                            issues[tank_id] = issues_for_fuel
                    continue
                amount = float(deduction) * share / len(active)
                for tank_id in active:
                    if allocations[tank_id] is not None:
                        allocations[tank_id] = float(allocations[tank_id]) + amount
    return allocations, issues


def estimate_tank_empty_time(
    tank_id: int, fuel_type: str | None, anchor_mass_mt: float | None, forecast_start_utc: datetime,
    intervals: list[FuelDepletionInterval], allocation_events: list[TankConsumptionAllocationEvent],
    tank_fuels: dict[int, str | None], transfers: list[InternalFuelTransfer] | None = None, receipts: list[BunkerTankReceipt] | None = None,
) -> tuple[datetime | None, str, str | None]:
    if anchor_mass_mt is None:
        return None, "UNAVAILABLE", "No mass-bearing sounding available"
    if fuel_type is None:
        return None, "UNAVAILABLE", "Fuel type unknown"
    mass = anchor_mass_mt
    if mass <= 0:
        return forecast_start_utc, "ALREADY_DEPLETED", "Tank is already depleted"
    events = sorted(allocation_events, key=lambda item: _utc(item.effective_at_utc))
    transfers = sorted(transfers or [], key=_transfer_time)
    receipts = sorted(receipts or [], key=lambda item: _utc(datetime.fromisoformat(item.effective_at_utc)))
    applied_transfers: set[int | None] = set()
    saw_active = False
    for interval in sorted(intervals, key=lambda item: _utc(item.start_utc)):
        start, end = max(_utc(interval.start_utc), _utc(forecast_start_utc)), _utc(interval.end_utc)
        if end <= start:
            continue
        deduction = interval.deductions_mt.get(fuel_type)
        if deduction is None:
            return None, "UNAVAILABLE", f"Authoritative {fuel_type} depletion is unavailable"
        duration = (_utc(interval.end_utc) - _utc(interval.start_utc)).total_seconds()
        if duration <= 0:
            continue
        boundaries = sorted({start, end, *(_utc(event.effective_at_utc) for event in events if start < _utc(event.effective_at_utc) < end), *(_transfer_time(item) for item in transfers if start <= _transfer_time(item) < end), *(_utc(datetime.fromisoformat(item.effective_at_utc)) for item in receipts if start <= _utc(datetime.fromisoformat(item.effective_at_utc)) < end)})
        for segment_start, segment_end in zip(boundaries, boundaries[1:]):
            for transfer in transfers:
                if transfer.id in applied_transfers or _transfer_time(transfer) > segment_start:
                    continue
                if transfer.from_tank_id == tank_id:
                    mass -= transfer.quantity_mt
                elif transfer.to_tank_id == tank_id:
                    mass += transfer.quantity_mt
                applied_transfers.add(transfer.id)
            for receipt in receipts:
                receipt_time = _utc(datetime.fromisoformat(receipt.effective_at_utc))
                if receipt.tank_id == tank_id and receipt_time == segment_start:
                    mass += receipt.quantity_mt
            if mass <= 0:
                return segment_start, "ESTIMATED", None
            active = [item for item in _state_at(events, segment_start) if tank_fuels.get(item) == fuel_type]
            if tank_id not in active:
                continue
            saw_active = True
            amount = float(deduction) * (segment_end - segment_start).total_seconds() / duration / len(active)
            if amount <= 0:
                continue
            if mass <= amount:
                fraction = mass / amount
                return segment_start + (segment_end - segment_start) * fraction, "ESTIMATED", None
            mass -= amount
    if not saw_active:
        return None, "UNAVAILABLE", f"No active {fuel_type} consumption tank selected"
    return None, "BEYOND_PLAN", "Beyond current voyage plan"


def _state_at(events: list[TankConsumptionAllocationEvent], instant: datetime) -> tuple[int, ...]:
    state: tuple[int, ...] = ()
    for event in events:
        if _utc(event.effective_at_utc) <= instant:
            state = event.tank_ids
        else:
            break
    return state


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _transfer_time(transfer: InternalFuelTransfer) -> datetime:
    value = datetime.fromisoformat(transfer.effective_at_utc())
    return _utc(value)
