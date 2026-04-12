"""Core feature-set builder for deterministic candidate scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from stock_trading_bot.ai.feature_builder import FeatureBuilder, HistoricalBar
from stock_trading_bot.core.models import CandidateSelectionResult, MarketDataSnapshot


@dataclass(slots=True, frozen=True, kw_only=True)
class PriceMomentumFeatures:
    """Momentum feature group derived from recent price movement."""

    short_window: int
    medium_window: int
    long_window: int
    short_return_rate: Decimal
    medium_return_rate: Decimal
    long_return_rate: Decimal
    gap_rate: Decimal

    def as_mapping(self) -> dict[str, Decimal]:
        """Return a flattened mapping representation."""

        return {
            f"return_{self.short_window}d": self.short_return_rate,
            f"return_{self.medium_window}d": self.medium_return_rate,
            f"return_{self.long_window}d": self.long_return_rate,
            "gap_rate": self.gap_rate,
        }


@dataclass(slots=True, frozen=True, kw_only=True)
class VolumeLiquidityFeatures:
    """Liquidity feature group derived from volume and trading value."""

    volume_average_window: int
    trading_value_average_window: int
    volume_ratio_to_average: Decimal
    trading_value_ratio_to_average: Decimal

    def as_mapping(self) -> dict[str, Decimal]:
        """Return a flattened mapping representation."""

        return {
            f"volume_ratio_{self.volume_average_window}d": self.volume_ratio_to_average,
            f"trading_value_ratio_{self.trading_value_average_window}d": (
                self.trading_value_ratio_to_average
            ),
        }


@dataclass(slots=True, frozen=True, kw_only=True)
class BreakoutPositionFeatures:
    """Breakout-position features anchored to the recent high."""

    breakout_lookback_days: int
    distance_from_lookback_high: Decimal
    close_strength_ratio: Decimal

    def as_mapping(self) -> dict[str, Decimal]:
        """Return a flattened mapping representation."""

        return {
            f"distance_from_{self.breakout_lookback_days}d_high": self.distance_from_lookback_high,
            "close_strength_ratio": self.close_strength_ratio,
        }


@dataclass(slots=True, frozen=True, kw_only=True)
class TrendVolatilityFeatures:
    """Trend and volatility feature group based on moving averages and RSI."""

    short_moving_average_name: str
    long_moving_average_name: str
    distance_from_short_moving_average: Decimal
    distance_from_long_moving_average: Decimal
    intraday_range_ratio: Decimal
    rsi_value: Decimal

    def as_mapping(self) -> dict[str, Decimal]:
        """Return a flattened mapping representation."""

        return {
            f"distance_from_{self.short_moving_average_name}": (
                self.distance_from_short_moving_average
            ),
            f"distance_from_{self.long_moving_average_name}": (
                self.distance_from_long_moving_average
            ),
            "intraday_range_ratio": self.intraday_range_ratio,
            "rsi_value": self.rsi_value,
        }


@dataclass(slots=True, frozen=True, kw_only=True)
class MarketContextFeatures:
    """Market-context proxy features available in the initial single-instrument setup."""

    filter_pass_ratio: Decimal
    trend_alignment_ratio: Decimal
    final_snapshot_score: Decimal

    def as_mapping(self) -> dict[str, Decimal]:
        """Return a flattened mapping representation."""

        return {
            "filter_pass_ratio": self.filter_pass_ratio,
            "trend_alignment_ratio": self.trend_alignment_ratio,
            "final_snapshot_score": self.final_snapshot_score,
        }


@dataclass(slots=True, frozen=True, kw_only=True)
class CoreFeatureSet:
    """Structured feature set used by the first-pass ranking model."""

    instrument_id: str
    candidate_ref: str
    timestamp: datetime
    feature_set_name: str
    price_momentum: PriceMomentumFeatures
    volume_liquidity: VolumeLiquidityFeatures
    breakout_position: BreakoutPositionFeatures
    trend_volatility: TrendVolatilityFeatures
    market_context: MarketContextFeatures

    def flatten(self) -> dict[str, Decimal]:
        """Return a single flattened mapping for debugging and analysis."""

        flattened: dict[str, Decimal] = {}
        grouped_features: tuple[tuple[str, Mapping[str, Decimal]], ...] = (
            ("price_momentum", self.price_momentum.as_mapping()),
            ("volume_liquidity", self.volume_liquidity.as_mapping()),
            ("breakout_position", self.breakout_position.as_mapping()),
            ("trend_volatility", self.trend_volatility.as_mapping()),
            ("market_context", self.market_context.as_mapping()),
        )
        for group_name, feature_values in grouped_features:
            for feature_name, feature_value in feature_values.items():
                flattened[f"{group_name}.{feature_name}"] = feature_value
        return flattened


@dataclass(slots=True, kw_only=True)
class CoreFeatureSetBuilder(FeatureBuilder):
    """Build the initial explainable feature groups for candidate ranking."""

    momentum_windows: tuple[int, int, int]
    volume_average_window: int
    trading_value_average_window: int
    breakout_lookback_days: int
    short_moving_average_name: str
    long_moving_average_name: str
    rsi_indicator_name: str

    def __post_init__(self) -> None:
        if len(self.momentum_windows) != 3 or any(window <= 0 for window in self.momentum_windows):
            raise ValueError("momentum_windows must contain exactly three positive integers.")
        if self.volume_average_window <= 0:
            raise ValueError("volume_average_window must be positive.")
        if self.trading_value_average_window <= 0:
            raise ValueError("trading_value_average_window must be positive.")
        if self.breakout_lookback_days <= 0:
            raise ValueError("breakout_lookback_days must be positive.")

    def build(
        self,
        candidate: CandidateSelectionResult,
        snapshot: MarketDataSnapshot,
        recent_bars: Sequence[HistoricalBar],
    ) -> CoreFeatureSet:
        """Build one `CoreFeatureSet` from the candidate, snapshot, and recent bars."""

        current_bar, prior_bars = self.current_and_prior_bars(snapshot, recent_bars)
        short_window, medium_window, long_window = self.momentum_windows
        price_momentum = PriceMomentumFeatures(
            short_window=short_window,
            medium_window=medium_window,
            long_window=long_window,
            short_return_rate=self._window_return(snapshot.close_price, prior_bars, short_window),
            medium_return_rate=self._window_return(snapshot.close_price, prior_bars, medium_window),
            long_return_rate=self._window_return(snapshot.close_price, prior_bars, long_window),
            gap_rate=self._gap_rate(current_bar, prior_bars),
        )
        volume_liquidity = VolumeLiquidityFeatures(
            volume_average_window=self.volume_average_window,
            trading_value_average_window=self.trading_value_average_window,
            volume_ratio_to_average=self._volume_ratio(current_bar, prior_bars),
            trading_value_ratio_to_average=self._trading_value_ratio(current_bar, prior_bars),
        )
        breakout_position = BreakoutPositionFeatures(
            breakout_lookback_days=self.breakout_lookback_days,
            distance_from_lookback_high=self._distance_from_lookback_high(current_bar, prior_bars),
            close_strength_ratio=self.safe_ratio(snapshot.close_price, snapshot.high_price),
        )
        short_moving_average = self.indicator_value(current_bar, self.short_moving_average_name)
        long_moving_average = self.indicator_value(current_bar, self.long_moving_average_name)
        trend_volatility = TrendVolatilityFeatures(
            short_moving_average_name=self.short_moving_average_name,
            long_moving_average_name=self.long_moving_average_name,
            distance_from_short_moving_average=self._distance_from_average(
                snapshot.close_price,
                short_moving_average,
            ),
            distance_from_long_moving_average=self._distance_from_average(
                snapshot.close_price,
                long_moving_average,
            ),
            intraday_range_ratio=self.safe_ratio(
                snapshot.high_price - snapshot.low_price,
                snapshot.close_price,
            ),
            rsi_value=self.indicator_value(current_bar, self.rsi_indicator_name) or Decimal("50"),
        )
        market_context = MarketContextFeatures(
            filter_pass_ratio=self._filter_pass_ratio(candidate),
            trend_alignment_ratio=self._trend_alignment_ratio(
                short_moving_average,
                long_moving_average,
            ),
            final_snapshot_score=Decimal("1") if snapshot.is_final else Decimal("0"),
        )
        return CoreFeatureSet(
            instrument_id=candidate.instrument_id,
            candidate_ref=candidate.candidate_id,
            timestamp=snapshot.timestamp,
            feature_set_name=self.feature_set_name,
            price_momentum=price_momentum,
            volume_liquidity=volume_liquidity,
            breakout_position=breakout_position,
            trend_volatility=trend_volatility,
            market_context=market_context,
        )

    def _window_return(
        self,
        current_close: Decimal,
        prior_bars: Sequence[HistoricalBar],
        window: int,
    ) -> Decimal:
        if len(prior_bars) < window:
            return Decimal("0")
        reference_bar = prior_bars[-window]
        return self.rate_of_return(current_close, reference_bar.close_price)

    def _gap_rate(
        self,
        current_bar: HistoricalBar,
        prior_bars: Sequence[HistoricalBar],
    ) -> Decimal:
        if not prior_bars:
            return Decimal("0")
        previous_close = prior_bars[-1].close_price
        return self.rate_of_return(current_bar.open_price, previous_close)

    def _volume_ratio(
        self,
        current_bar: HistoricalBar,
        prior_bars: Sequence[HistoricalBar],
    ) -> Decimal:
        reference_bars = prior_bars[-self.volume_average_window :]
        return self.safe_ratio(Decimal(current_bar.volume), self.average_volume(reference_bars))

    def _trading_value_ratio(
        self,
        current_bar: HistoricalBar,
        prior_bars: Sequence[HistoricalBar],
    ) -> Decimal:
        reference_bars = prior_bars[-self.trading_value_average_window :]
        return self.safe_ratio(
            current_bar.trading_value,
            self.average_trading_value(reference_bars),
        )

    def _distance_from_lookback_high(
        self,
        current_bar: HistoricalBar,
        prior_bars: Sequence[HistoricalBar],
    ) -> Decimal:
        reference_bars = prior_bars[-self.breakout_lookback_days :]
        if not reference_bars:
            return Decimal("0")
        lookback_high = max(bar.high_price for bar in reference_bars)
        return self.rate_of_return(current_bar.close_price, lookback_high)

    def _distance_from_average(
        self,
        close_price: Decimal,
        moving_average: Decimal | None,
    ) -> Decimal:
        return self.rate_of_return(close_price, moving_average)

    @staticmethod
    def _filter_pass_ratio(candidate: CandidateSelectionResult) -> Decimal:
        total_filters = len(candidate.passed_filters) + len(candidate.failed_filters)
        if total_filters == 0:
            return Decimal("1") if candidate.passed else Decimal("0")
        return Decimal(len(candidate.passed_filters)) / Decimal(total_filters)

    def _trend_alignment_ratio(
        self,
        short_moving_average: Decimal | None,
        long_moving_average: Decimal | None,
    ) -> Decimal:
        if short_moving_average is None or long_moving_average is None:
            return Decimal("0")
        return self.rate_of_return(short_moving_average, long_moving_average)
