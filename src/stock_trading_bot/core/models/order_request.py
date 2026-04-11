"""Order request contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

OrderSide = Literal["buy", "sell"]


@dataclass(slots=True, kw_only=True)
class OrderRequest:
    """Standardized order intent before broker submission."""

    order_request_id: str
    instrument_id: str
    timestamp: datetime
    side: OrderSide
    order_type: str
    quantity: Decimal
    price: Decimal
    time_in_force: str
    source_signal_id: str
    risk_check_ref: str
    broker_mode: str
    request_reason: str

