"""Order event contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(slots=True, kw_only=True)
class OrderEvent:
    """Normalized event representing order status or fill changes."""

    order_event_id: str
    order_request_id: str
    timestamp: datetime
    event_type: str
    broker_order_id: str
    filled_quantity: Decimal
    filled_price_avg: Decimal
    remaining_quantity: Decimal
    event_message: str
    is_terminal: bool

