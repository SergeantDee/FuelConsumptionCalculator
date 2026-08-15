from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class PortTimezone:
    port: str
    timezone_id: str


@dataclass(frozen=True, slots=True)
class TimeConversionResult:
    utc_value: datetime | None
    timezone_id: str | None
    status: str
    message: str = ""


DEFAULT_PORT_TIMEZONES: dict[str, str] = {
    "Santos": "America/Sao_Paulo",
    "Itapoa": "America/Sao_Paulo",
    "Paranagua": "America/Sao_Paulo",
    "Rio de Janeiro": "America/Sao_Paulo",
    "Pecem": "America/Fortaleza",
    "Port Tangier Mediterranee": "Africa/Casablanca",
    "Tanger Med": "Africa/Casablanca",
    "Tangier": "Africa/Casablanca",
    "Rotterdam": "Europe/Amsterdam",
    "Antwerp": "Europe/Brussels",
    "London Gateway": "Europe/London",
    "Southampton": "Europe/London",
    "Bremerhaven": "Europe/Berlin",
    "Hamburg": "Europe/Berlin",
    "Algeciras": "Europe/Madrid",
}


def normalize_port_name(port: str) -> str:
    return " ".join(port.strip().split()).casefold()


def local_to_utc(local_value: datetime | None, timezone_id: str | None) -> TimeConversionResult:
    if local_value is None:
        return TimeConversionResult(None, timezone_id, "UNRESOLVED", "Timestamp is empty.")
    if not timezone_id:
        return TimeConversionResult(None, None, "UNRESOLVED", "Port timezone is not configured.")
    if local_value.tzinfo is not None:
        return TimeConversionResult(local_value.astimezone(timezone.utc), timezone_id, "RESOLVED")
    try:
        zone = ZoneInfo(timezone_id)
    except Exception as exc:
        return TimeConversionResult(None, timezone_id, "INVALID_TIMEZONE", str(exc))

    candidates: list[datetime] = []
    offsets = set()
    for fold in (0, 1):
        aware = local_value.replace(tzinfo=zone, fold=fold)
        offsets.add(aware.utcoffset())
        roundtrip = aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
        if roundtrip == local_value:
            candidates.append(aware)
    unique_utc = {candidate.astimezone(timezone.utc) for candidate in candidates}
    if not candidates:
        return TimeConversionResult(None, timezone_id, "NONEXISTENT_LOCAL_TIME", "Local time does not exist in this timezone.")
    if len(unique_utc) > 1 and len(offsets) > 1:
        return TimeConversionResult(None, timezone_id, "AMBIGUOUS_LOCAL_TIME", "Local time is ambiguous in this timezone.")
    return TimeConversionResult(candidates[0].astimezone(timezone.utc), timezone_id, "RESOLVED")


def utc_to_vessel_time(utc_value: datetime, offset_minutes: int) -> datetime:
    aware = utc_value if utc_value.tzinfo else utc_value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).replace(tzinfo=None) + timedelta(minutes=offset_minutes)
