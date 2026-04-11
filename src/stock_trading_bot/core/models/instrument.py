"""Instrument contract."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, kw_only=True)
class Instrument:
    """Standardized instrument identity used across all modules."""

    instrument_id: str
    symbol: str
    name: str
    market: str
    asset_type: str
    sector: str
    is_etf: bool
    is_active: bool

