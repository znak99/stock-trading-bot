"""Signal contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

SignalType = Literal["buy", "sell", "partial_sell"]


@dataclass(slots=True, kw_only=True)
class Signal:
    """Execution-prepared strategy signal shared across modules."""

    signal_id: str
    instrument_id: str
    timestamp: datetime
    signal_type: SignalType
    strategy_name: str
    signal_strength: Decimal
    decision_reason: str
    market_snapshot_ref: str
    candidate_ref: str
    target_execution_time: datetime
    is_confirmed: bool

