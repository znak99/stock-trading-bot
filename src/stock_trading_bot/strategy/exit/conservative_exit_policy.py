"""Conservative exit policy implementation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from stock_trading_bot.core.models import MarketDataSnapshot, Position, Signal
from stock_trading_bot.market.services import EnrichedHistoricalBar, HistoricalOhlcvBar
from stock_trading_bot.strategy.services import SignalFactory


HistoricalBar = HistoricalOhlcvBar | EnrichedHistoricalBar
HistoricalBarsProvider = Callable[[str, MarketDataSnapshot], Sequence[HistoricalBar]]
PartialTakeProfitProvider = Callable[[Position], bool]


def _default_partial_take_profit_provider(position: Position) -> bool:
    del position
    return False


@dataclass(slots=True, kw_only=True)
class ConservativeExitPolicy:
    """Fixed stop-loss plus partial take-profit and trend-following exit policy."""

    recent_bars_provider: HistoricalBarsProvider
    signal_factory: SignalFactory
    has_partial_take_profit_provider: PartialTakeProfitProvider = _default_partial_take_profit_provider
    name: str = "conservative_exit_policy"
    stop_loss_rate: Decimal = Decimal("-0.025")
    first_take_profit_rate: Decimal = Decimal("0.035")
    first_take_profit_fraction: Decimal = Decimal("0.5")
    remainder_exit_ma_window: int = 5
    use_final_snapshot_only: bool = True

    def __post_init__(self) -> None:
        if self.stop_loss_rate >= Decimal("0"):
            raise ValueError("stop_loss_rate must be negative.")
        if self.first_take_profit_rate <= Decimal("0"):
            raise ValueError("first_take_profit_rate must be positive.")
        if self.first_take_profit_fraction <= Decimal("0") or self.first_take_profit_fraction >= Decimal("1"):
            raise ValueError("first_take_profit_fraction must be between 0 and 1.")
        if self.remainder_exit_ma_window <= 0:
            raise ValueError("remainder_exit_ma_window must be positive.")

    def evaluate(
        self,
        position: Position,
        snapshot: MarketDataSnapshot,
    ) -> tuple[Signal, ...]:
        """Return zero or one exit signal for the provided position and snapshot."""

        if position.position_status != "open":
            return ()
        if self.use_final_snapshot_only and not snapshot.is_final:
            return ()
        if position.instrument_id != snapshot.instrument_id:
            return ()
        if position.avg_entry_price <= Decimal("0"):
            return ()

        pnl_rate = (snapshot.close_price - position.avg_entry_price) / position.avg_entry_price
        if pnl_rate <= self.stop_loss_rate:
            return (
                self.signal_factory.create_exit_signal(
                    position=position,
                    snapshot=snapshot,
                    signal_type="sell",
                    signal_strength=Decimal("1"),
                    decision_reason=(
                        f"stop_loss_triggered(pnl_rate={pnl_rate},threshold={self.stop_loss_rate})"
                    ),
                ),
            )

        has_partial_take_profit = self.has_partial_take_profit_provider(position)
        if not has_partial_take_profit and pnl_rate >= self.first_take_profit_rate:
            return (
                self.signal_factory.create_exit_signal(
                    position=position,
                    snapshot=snapshot,
                    signal_type="partial_sell",
                    signal_strength=Decimal("1"),
                    decision_reason=(
                        "take_profit_triggered("
                        f"pnl_rate={pnl_rate},threshold={self.first_take_profit_rate},"
                        f"fraction={self.first_take_profit_fraction})"
                    ),
                ),
            )

        if has_partial_take_profit:
            moving_average = self._calculate_trailing_moving_average(snapshot, position.instrument_id)
            if moving_average is not None and snapshot.close_price < moving_average:
                return (
                    self.signal_factory.create_exit_signal(
                        position=position,
                        snapshot=snapshot,
                        signal_type="sell",
                        signal_strength=Decimal("1"),
                        decision_reason=(
                            f"trend_exit_triggered(close={snapshot.close_price},"
                            f"sma_{self.remainder_exit_ma_window}={moving_average})"
                        ),
                    ),
                )

        return ()

    def _calculate_trailing_moving_average(
        self,
        snapshot: MarketDataSnapshot,
        instrument_id: str,
    ) -> Decimal | None:
        recent_bars = tuple(
            bar
            for bar in sorted(
                self.recent_bars_provider(instrument_id, snapshot),
                key=lambda current_bar: current_bar.timestamp,
            )
            if bar.timestamp < snapshot.timestamp
        )
        required_prior_bars = self.remainder_exit_ma_window - 1
        if len(recent_bars) < required_prior_bars:
            return None

        closing_prices = [bar.close_price for bar in recent_bars[-required_prior_bars:]]
        closing_prices.append(snapshot.close_price)
        return sum(closing_prices, Decimal("0")) / Decimal(self.remainder_exit_ma_window)
