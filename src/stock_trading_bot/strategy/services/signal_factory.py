"""Signal creation helpers for strategy components."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from typing import Literal

from stock_trading_bot.core.models import CandidateSelectionResult, MarketDataSnapshot, Position, Signal


class SignalFactory:
    """Create standardized strategy signals."""

    def __init__(
        self,
        *,
        strategy_name: str,
        execution_hour: int = 9,
        execution_minute: int = 0,
    ) -> None:
        self._strategy_name = strategy_name
        self._execution_hour = execution_hour
        self._execution_minute = execution_minute

    def create_buy_signal(
        self,
        *,
        candidate: CandidateSelectionResult,
        snapshot: MarketDataSnapshot,
        signal_strength: Decimal,
        decision_reason: str,
        is_confirmed: bool = True,
    ) -> Signal:
        """Create a buy signal scheduled for the next market open."""

        bounded_signal_strength = min(Decimal("1"), max(Decimal("0"), signal_strength))
        return Signal(
            signal_id=(
                f"signal:{self._strategy_name}:{candidate.candidate_id}:{snapshot.snapshot_id}:buy"
            ),
            instrument_id=candidate.instrument_id,
            timestamp=snapshot.timestamp,
            signal_type="buy",
            strategy_name=self._strategy_name,
            signal_strength=bounded_signal_strength,
            decision_reason=decision_reason,
            market_snapshot_ref=snapshot.snapshot_id,
            candidate_ref=candidate.candidate_id,
            target_execution_time=self._build_next_open_execution_time(snapshot),
            is_confirmed=is_confirmed,
        )

    def create_exit_signal(
        self,
        *,
        position: Position,
        snapshot: MarketDataSnapshot,
        signal_type: Literal["sell", "partial_sell"],
        signal_strength: Decimal,
        decision_reason: str,
        is_confirmed: bool = True,
    ) -> Signal:
        """Create a sell or partial-sell signal scheduled for the next market open."""

        bounded_signal_strength = min(Decimal("1"), max(Decimal("0"), signal_strength))
        return Signal(
            signal_id=(
                f"signal:{self._strategy_name}:{position.position_id}:{snapshot.snapshot_id}:{signal_type}"
            ),
            instrument_id=position.instrument_id,
            timestamp=snapshot.timestamp,
            signal_type=signal_type,
            strategy_name=self._strategy_name,
            signal_strength=bounded_signal_strength,
            decision_reason=decision_reason,
            market_snapshot_ref=snapshot.snapshot_id,
            candidate_ref=position.position_id,
            target_execution_time=self._build_next_open_execution_time(snapshot),
            is_confirmed=is_confirmed,
        )

    def _build_next_open_execution_time(self, snapshot: MarketDataSnapshot):
        next_calendar_day = snapshot.timestamp + timedelta(days=1)
        return next_calendar_day.replace(
            hour=self._execution_hour,
            minute=self._execution_minute,
            second=0,
            microsecond=0,
        )
