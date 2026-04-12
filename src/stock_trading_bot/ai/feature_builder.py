"""Shared feature-builder helpers for AI scoring."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from stock_trading_bot.core.models import CandidateSelectionResult, MarketDataSnapshot
from stock_trading_bot.market.services import EnrichedHistoricalBar, HistoricalOhlcvBar

HistoricalBar = HistoricalOhlcvBar | EnrichedHistoricalBar


@dataclass(slots=True, kw_only=True)
class FeatureBuilder:
    """Base helper with deterministic utilities for feature extraction."""

    feature_set_name: str

    def build(
        self,
        candidate: CandidateSelectionResult,
        snapshot: MarketDataSnapshot,
        recent_bars: Sequence[HistoricalBar],
    ) -> object:
        """Build one feature object from a candidate and recent bars."""

        raise NotImplementedError("Concrete feature builders must implement build().")

    @staticmethod
    def ordered_bars(recent_bars: Sequence[HistoricalBar]) -> tuple[HistoricalBar, ...]:
        """Return bars ordered by timestamp."""

        return tuple(sorted(recent_bars, key=lambda bar: bar.timestamp))

    @staticmethod
    def current_and_prior_bars(
        snapshot: MarketDataSnapshot,
        recent_bars: Sequence[HistoricalBar],
    ) -> tuple[HistoricalBar, tuple[HistoricalBar, ...]]:
        """Resolve the current bar plus all bars strictly earlier than the snapshot."""

        ordered_bars = FeatureBuilder.ordered_bars(recent_bars)
        current_bar = next(
            (bar for bar in reversed(ordered_bars) if bar.timestamp <= snapshot.timestamp),
            None,
        )
        if current_bar is None:
            raise ValueError(
                "Recent bars must include at least one bar on or before the snapshot timestamp. "
                "instrument_id="
                f"{snapshot.instrument_id}, timestamp={snapshot.timestamp.isoformat()}"
            )
        prior_bars = tuple(bar for bar in ordered_bars if bar.timestamp < current_bar.timestamp)
        return current_bar, prior_bars

    @staticmethod
    def safe_ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
        """Return a zero-safe decimal ratio."""

        if denominator == Decimal("0"):
            return Decimal("0")
        return numerator / denominator

    @staticmethod
    def clamp(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
        """Clamp a decimal value to the requested bounds."""

        return min(upper, max(lower, value))

    @staticmethod
    def average_decimal(values: Sequence[Decimal]) -> Decimal:
        """Return the arithmetic mean for a non-empty decimal sequence."""

        if not values:
            return Decimal("0")
        return sum(values, Decimal("0")) / Decimal(len(values))

    @staticmethod
    def average_volume(bars: Sequence[HistoricalBar]) -> Decimal:
        """Return the average volume across the provided bars."""

        if not bars:
            return Decimal("0")
        return sum((Decimal(bar.volume) for bar in bars), Decimal("0")) / Decimal(len(bars))

    @staticmethod
    def average_trading_value(bars: Sequence[HistoricalBar]) -> Decimal:
        """Return the average trading value across the provided bars."""

        if not bars:
            return Decimal("0")
        return sum((bar.trading_value for bar in bars), Decimal("0")) / Decimal(len(bars))

    @staticmethod
    def rate_of_return(current_close: Decimal, reference_close: Decimal | None) -> Decimal:
        """Return close-to-close return from a reference price."""

        if reference_close in {None, Decimal("0")}:
            return Decimal("0")
        return (current_close / reference_close) - Decimal("1")

    @staticmethod
    def indicator_value(bar: HistoricalBar, indicator_name: str) -> Decimal | None:
        """Return one indicator value from an enriched bar if present."""

        indicators = getattr(bar, "indicators", None)
        if not isinstance(indicators, dict):
            return None
        indicator_value = indicators.get(indicator_name)
        return indicator_value if isinstance(indicator_value, Decimal) else None
