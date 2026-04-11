"""Exit policy interface contract."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from stock_trading_bot.core.models import MarketDataSnapshot, Position, Signal


@runtime_checkable
class ExitPolicy(Protocol):
    """Exit policy contract for sell and partial-sell decisions."""

    name: str

    def evaluate(
        self,
        position: Position,
        snapshot: MarketDataSnapshot,
    ) -> Sequence[Signal]:
        """Generate zero or more exit signals for an active position."""

