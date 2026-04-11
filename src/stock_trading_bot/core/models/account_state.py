"""Account state contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(slots=True, kw_only=True)
class AccountState:
    """Standardized account snapshot plus internal bookkeeping extensions."""

    account_state_id: str
    timestamp: datetime
    broker_mode: str
    total_equity: Decimal
    cash_balance: Decimal
    available_cash: Decimal
    market_value: Decimal
    active_position_count: int
    max_position_limit: int
    account_status: str
    reserved_cash: Decimal = Decimal("0")
    reserved_sell_quantity: dict[str, Decimal] = field(default_factory=dict)
    realized_pnl: Decimal = Decimal("0")
    accumulated_buy_commission: Decimal = Decimal("0")
    accumulated_sell_commission: Decimal = Decimal("0")
    accumulated_sell_tax: Decimal = Decimal("0")
    accumulated_slippage_cost_estimate: Decimal = Decimal("0")

