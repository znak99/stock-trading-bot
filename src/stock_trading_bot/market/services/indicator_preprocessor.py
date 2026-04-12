"""Indicator preprocessing for historical OHLCV bars."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


IndicatorValue = Decimal | None


@dataclass(slots=True, frozen=True, kw_only=True)
class HistoricalOhlcvBar:
    """Typed OHLCV row used as the input for indicator calculations."""

    instrument_id: str
    timestamp: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    trading_value: Decimal
    change_rate: Decimal


@dataclass(slots=True, frozen=True, kw_only=True)
class EnrichedHistoricalBar:
    """Historical bar with precomputed indicator values."""

    instrument_id: str
    timestamp: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    trading_value: Decimal
    change_rate: Decimal
    indicators: dict[str, IndicatorValue]

    @classmethod
    def from_bar(
        cls,
        bar: HistoricalOhlcvBar,
        *,
        indicators: dict[str, IndicatorValue],
    ) -> EnrichedHistoricalBar:
        """Attach indicators to an existing OHLCV bar."""

        return cls(
            instrument_id=bar.instrument_id,
            timestamp=bar.timestamp,
            open_price=bar.open_price,
            high_price=bar.high_price,
            low_price=bar.low_price,
            close_price=bar.close_price,
            volume=bar.volume,
            trading_value=bar.trading_value,
            change_rate=bar.change_rate,
            indicators=indicators,
        )


class IndicatorPreprocessor:
    """Compute strategy-ready indicators from historical bars."""

    def __init__(
        self,
        *,
        moving_average_windows: Sequence[int] = (5, 20),
        rsi_period: int = 14,
    ) -> None:
        normalized_windows = tuple(dict.fromkeys(moving_average_windows))
        if not normalized_windows or any(window <= 0 for window in normalized_windows):
            raise ValueError("moving_average_windows must contain positive integers.")
        if rsi_period <= 0:
            raise ValueError("rsi_period must be a positive integer.")

        self._moving_average_windows = normalized_windows
        self._rsi_period = rsi_period

    @property
    def indicator_names(self) -> tuple[str, ...]:
        """Return the indicator names produced by this preprocessor."""

        moving_average_names = tuple(f"sma_{window}" for window in self._moving_average_windows)
        return (*moving_average_names, f"rsi_{self._rsi_period}")

    def preprocess(self, bars: Sequence[HistoricalOhlcvBar]) -> tuple[EnrichedHistoricalBar, ...]:
        """Return bars enriched with moving-average and RSI values."""

        if not bars:
            return ()

        close_prices = [bar.close_price for bar in bars]
        moving_average_values = {
            f"sma_{window}": self._calculate_simple_moving_average(close_prices, window)
            for window in self._moving_average_windows
        }
        rsi_name = f"rsi_{self._rsi_period}"
        rsi_values = self._calculate_rsi(close_prices, self._rsi_period)

        enriched_bars: list[EnrichedHistoricalBar] = []
        for index, bar in enumerate(bars):
            indicators = {
                indicator_name: values[index]
                for indicator_name, values in moving_average_values.items()
            }
            indicators[rsi_name] = rsi_values[index]
            enriched_bars.append(EnrichedHistoricalBar.from_bar(bar, indicators=indicators))

        return tuple(enriched_bars)

    @staticmethod
    def _calculate_simple_moving_average(
        values: Sequence[Decimal],
        window: int,
    ) -> tuple[IndicatorValue, ...]:
        moving_averages: list[IndicatorValue] = [None] * len(values)
        rolling_sum = Decimal("0")
        decimal_window = Decimal(window)

        for index, value in enumerate(values):
            rolling_sum += value
            if index >= window:
                rolling_sum -= values[index - window]
            if index + 1 >= window:
                moving_averages[index] = rolling_sum / decimal_window

        return tuple(moving_averages)

    @staticmethod
    def _calculate_rsi(values: Sequence[Decimal], period: int) -> tuple[IndicatorValue, ...]:
        rsi_values: list[IndicatorValue] = [None] * len(values)
        if len(values) <= period:
            return tuple(rsi_values)

        deltas = [values[index] - values[index - 1] for index in range(1, len(values))]
        gains = [delta if delta > Decimal("0") else Decimal("0") for delta in deltas]
        losses = [(-delta) if delta < Decimal("0") else Decimal("0") for delta in deltas]

        decimal_period = Decimal(period)
        period_minus_one = Decimal(period - 1)
        average_gain = sum(gains[:period], Decimal("0")) / decimal_period
        average_loss = sum(losses[:period], Decimal("0")) / decimal_period
        rsi_values[period] = IndicatorPreprocessor._resolve_rsi(average_gain, average_loss)

        for index in range(period + 1, len(values)):
            gain = gains[index - 1]
            loss = losses[index - 1]
            average_gain = ((average_gain * period_minus_one) + gain) / decimal_period
            average_loss = ((average_loss * period_minus_one) + loss) / decimal_period
            rsi_values[index] = IndicatorPreprocessor._resolve_rsi(average_gain, average_loss)

        return tuple(rsi_values)

    @staticmethod
    def _resolve_rsi(average_gain: Decimal, average_loss: Decimal) -> Decimal:
        if average_gain == Decimal("0") and average_loss == Decimal("0"):
            return Decimal("50")
        if average_loss == Decimal("0"):
            return Decimal("100")
        if average_gain == Decimal("0"):
            return Decimal("0")

        relative_strength = average_gain / average_loss
        return Decimal("100") - (Decimal("100") / (Decimal("1") + relative_strength))
