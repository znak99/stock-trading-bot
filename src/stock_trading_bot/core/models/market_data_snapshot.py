"""Market data snapshot contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(slots=True, kw_only=True)
class MarketDataSnapshot:
    """Standardized snapshot for intraday and final market data."""

    snapshot_id: str
    instrument_id: str
    timestamp: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    trading_value: Decimal
    change_rate: Decimal
    is_final: bool
    session_phase: str

