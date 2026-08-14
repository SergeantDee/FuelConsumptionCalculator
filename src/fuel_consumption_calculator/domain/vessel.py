from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Vessel:
    id: int | None
    name: str
    imo: str
    created_at: str | None = None
    updated_at: str | None = None
