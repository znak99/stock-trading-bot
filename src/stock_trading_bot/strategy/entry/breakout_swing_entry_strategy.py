"""Breakout swing entry strategy implementation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from stock_trading_bot.core.models import CandidateSelectionResult, MarketDataSnapshot, Position, Signal
from stock_trading_bot.market.services import EnrichedHistoricalBar, HistoricalOhlcvBar
from stock_trading_bot.strategy.services import CloseConfirmationEngine, SignalFactory


HistoricalBar = HistoricalOhlcvBar | EnrichedHistoricalBar
HistoricalBarsProvider = Callable[[str, MarketDataSnapshot], Sequence[HistoricalBar]]


@dataclass(slots=True, kw_only=True)
class BreakoutSwingEntryStrategy:
    """Rule-based breakout swing entry strategy."""

    recent_bars_provider: HistoricalBarsProvider
    close_confirmation_engine: CloseConfirmationEngine
    signal_factory: SignalFactory
    name: str = "breakout_swing_v1"
    use_final_snapshot_only: bool = True

    def evaluate_entry(
        self,
        candidate: CandidateSelectionResult,
        snapshot: MarketDataSnapshot,
    ) -> Signal | None:
        """Return a buy signal when the close-confirmed breakout remains valid."""

        if not candidate.passed:
            return None
        if self.use_final_snapshot_only and not snapshot.is_final:
            return None
        if candidate.market_snapshot_ref != snapshot.snapshot_id:
            return None

        recent_bars = tuple(self.recent_bars_provider(candidate.instrument_id, snapshot))
        confirmation = self.close_confirmation_engine.confirm(snapshot, recent_bars)
        if not confirmation.passed:
            return None

        signal_strength = self._calculate_signal_strength(
            volume_ratio=confirmation.volume_ratio,
            close_strength_ratio=confirmation.close_strength_ratio,
            close_price=snapshot.close_price,
            lookback_high=confirmation.lookback_high,
        )
        decision_reason = "; ".join(confirmation.reasons)
        return self.signal_factory.create_buy_signal(
            candidate=candidate,
            snapshot=snapshot,
            signal_strength=signal_strength,
            decision_reason=decision_reason,
            is_confirmed=True,
        )

    def evaluate_exit(
        self,
        position: Position,
        snapshot: MarketDataSnapshot,
    ) -> tuple[Signal, ...]:
        """Entry strategy does not generate exit signals directly."""

        del position, snapshot
        return ()

    def _calculate_signal_strength(
        self,
        *,
        volume_ratio: Decimal | None,
        close_strength_ratio: Decimal,
        close_price: Decimal,
        lookback_high: Decimal | None,
    ) -> Decimal:
        if lookback_high in {None, Decimal("0")} or volume_ratio is None:
            return Decimal("0")

        price_component = min(Decimal("1"), close_price / lookback_high)
        volume_component = min(
            Decimal("1"),
            volume_ratio / self.close_confirmation_engine.volume_ratio_target,
        )
        close_component = min(Decimal("1"), close_strength_ratio)
        return (price_component + volume_component + close_component) / Decimal("3")
