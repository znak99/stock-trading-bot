"""Position contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

PositionStatus = Literal["open", "closed"]


@dataclass(slots=True, kw_only=True)
class Position:
    """Standardized representation of a held or closed position."""

    position_id: str
    instrument_id: str
    opened_at: datetime
    updated_at: datetime
    quantity: Decimal
    avg_entry_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_rate: Decimal
    position_status: PositionStatus
    exit_policy_name: str

