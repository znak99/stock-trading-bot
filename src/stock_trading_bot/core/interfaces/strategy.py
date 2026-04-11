"""Strategy interface contract."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from stock_trading_bot.core.models import (
    CandidateSelectionResult,
    MarketDataSnapshot,
    Position,
    Signal,
)


@runtime_checkable
class Strategy(Protocol):
    """Strategy engine contract for entry and exit signal generation."""

    name: str

    def evaluate_entry(
        self,
        candidate: CandidateSelectionResult,
        snapshot: MarketDataSnapshot,
    ) -> Signal | None:
        """Evaluate whether a candidate should produce a buy signal."""

    def evaluate_exit(
        self,
        position: Position,
        snapshot: MarketDataSnapshot,
    ) -> Sequence[Signal]:
        """Evaluate whether an open position should produce sell signals."""

