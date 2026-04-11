"""Equal-weight allocation policy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

from stock_trading_bot.core.models import AccountState


@dataclass(slots=True, kw_only=True)
class EqualWeightAllocationPolicy:
    """Allocate capital using a fixed ratio of account equity."""

    max_position_ratio: Decimal = Decimal("0.20")
    lot_size: Decimal = Decimal("1")

    def target_capital(self, account_state: AccountState) -> Decimal:
        """Return the target capital budget for a single position."""

        return account_state.total_equity * self.max_position_ratio

    def quantity_for_capital(self, unit_price: Decimal, capital_budget: Decimal) -> Decimal:
        """Return the largest lot-aligned quantity within the capital budget."""

        if unit_price <= Decimal("0") or capital_budget <= Decimal("0"):
            return Decimal("0")

        raw_quantity = capital_budget / unit_price
        lot_count = (raw_quantity / self.lot_size).to_integral_value(rounding=ROUND_DOWN)
        quantity = lot_count * self.lot_size
        return max(quantity, Decimal("0"))
