from __future__ import annotations

from datetime import datetime, timedelta, timezone


MIN_OFFSET_MINUTES = -12 * 60
MAX_OFFSET_MINUTES = 14 * 60

# Recognized civil offsets currently used around the world, including the
# practical half-hour and quarter-hour ship-clock choices.
VESSEL_GMT_OFFSETS_MINUTES = (
    -720, -660, -600, -570, -540, -480, -420, -360, -300, -240, -210,
    -180, -150, -120, -60, 0, 60, 120, 180, 210, 240, 270, 300, 330, 345,
    360, 390, 420, 480, 525, 540, 570, 600, 630, 660, 720, 765, 780, 825,
    840,
)


def clamp_offset_minutes(minutes: int) -> int:
    return max(MIN_OFFSET_MINUTES, min(MAX_OFFSET_MINUTES, int(minutes)))


def format_gmt_offset(minutes: int) -> str:
    normalized = clamp_offset_minutes(minutes)
    sign = "+" if normalized >= 0 else "-"
    hours, remainder = divmod(abs(normalized), 60)
    return f"GMT {sign}{hours:02d}:{remainder:02d}"


def vessel_local_time(utc_now: datetime, offset_minutes: int) -> datetime:
    aware_utc = utc_now.astimezone(timezone.utc) if utc_now.tzinfo else utc_now.replace(tzinfo=timezone.utc)
    return aware_utc + timedelta(minutes=clamp_offset_minutes(offset_minutes))
