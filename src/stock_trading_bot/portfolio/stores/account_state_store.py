"""Account state storage."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from stock_trading_bot.core.models import AccountState

from .position_book import PositionBook


class AccountStateStore:
    """Mutable store for the latest account snapshot."""

    def __init__(self, account_state: AccountState) -> None:
        self._account_state = account_state
        self.sync_available_cash()

    def get_state(self) -> AccountState:
        """Return the current account state."""

        return self._account_state

    def replace_state(self, account_state: AccountState) -> None:
        """Replace the stored account state."""

        self._account_state = account_state
        self.sync_available_cash()

    def update_timestamp(self, timestamp: datetime) -> None:
        """Update the account state timestamp."""

        self._account_state.timestamp = timestamp

    def sync_available_cash(self) -> None:
        """Keep available cash consistent with cash and reserved cash."""

        self._account_state.available_cash = self._account_state.cash_balance - self._account_state.reserved_cash

    def recalculate_summary(self, position_book: PositionBook) -> None:
        """Recalculate account summary values from positions."""

        self._account_state.market_value = position_book.total_market_value()
        self._account_state.total_equity = self._account_state.cash_balance + self._account_state.market_value
        self._account_state.active_position_count = position_book.active_position_count()
        self.sync_available_cash()

    def increase_reserved_cash(self, amount: Decimal) -> None:
        """Increase reserved cash."""

        self._account_state.reserved_cash += amount
        self.sync_available_cash()

    def decrease_reserved_cash(self, amount: Decimal) -> None:
        """Decrease reserved cash without dropping below zero."""

        self._account_state.reserved_cash = max(
            Decimal("0"),
            self._account_state.reserved_cash - amount,
        )
        self.sync_available_cash()

