"""Filter interface contract."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stock_trading_bot.core.models import Instrument, MarketDataSnapshot


@runtime_checkable
class Filter(Protocol):
    """Single filter contract used by universe selection."""

    name: str

    def evaluate(
        self,
        instrument: Instrument,
        snapshot: MarketDataSnapshot,
    ) -> tuple[bool, str]:
        """Return pass/fail and a reason string for the evaluated candidate."""

