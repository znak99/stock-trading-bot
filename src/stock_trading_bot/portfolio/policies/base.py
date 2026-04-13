"""Portfolio allocation policy contracts."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from stock_trading_bot.core.models import AccountState, ScoreResult


class AllocationPolicy(Protocol):
    """Common contract for capital-allocation policies."""

    lot_size: Decimal
    max_position_ratio: Decimal

    def target_capital(
        self,
        account_state: AccountState,
        *,
        score_result: ScoreResult | None = None,
    ) -> Decimal:
        """Return the desired capital budget for one position."""

    def quantity_for_capital(self, unit_price: Decimal, capital_budget: Decimal) -> Decimal:
        """Return a lot-aligned quantity within the provided capital budget."""
