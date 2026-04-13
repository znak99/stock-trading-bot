"""Initial deterministic ranking model for candidate prioritization."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from stock_trading_bot.ai.core_feature_set_builder import CoreFeatureSet, CoreFeatureSetBuilder
from stock_trading_bot.ai.feature_builder import HistoricalBar
from stock_trading_bot.core.models import CandidateSelectionResult, MarketDataSnapshot, ScoreResult

RecentBarsProvider = Callable[[str, MarketDataSnapshot], Sequence[HistoricalBar]]


@dataclass(slots=True, kw_only=True)
class BasicRankingModel:
    """Explainable weighted-scoring model used for the initial AI pass."""

    recent_bars_provider: RecentBarsProvider
    core_feature_set_builder: CoreFeatureSetBuilder
    group_weights: dict[str, Decimal]
    price_return_cap: Decimal
    gap_rate_cap: Decimal
    volume_ratio_target: Decimal
    trading_value_ratio_target: Decimal
    breakout_distance_cap: Decimal
    close_strength_min: Decimal
    close_strength_target: Decimal
    trend_gap_cap: Decimal
    max_intraday_range_ratio: Decimal
    rsi_neutral_floor: Decimal
    rsi_neutral_ceiling: Decimal
    trend_alignment_cap: Decimal
    name: str = "basic_ranking_model"
    version: str = "v1"

    def __post_init__(self) -> None:
        required_groups = {
            "price_momentum",
            "volume_liquidity",
            "breakout_position",
            "trend_volatility",
            "market_context",
        }
        if set(self.group_weights) != required_groups:
            raise ValueError(
                "group_weights must define exactly the five core feature groups. "
                f"received={tuple(sorted(self.group_weights))}"
            )
        if sum(self.group_weights.values(), Decimal("0")) <= Decimal("0"):
            raise ValueError("group_weights must sum to a positive value.")

    def score_candidate(
        self,
        candidate: CandidateSelectionResult,
        snapshot: MarketDataSnapshot,
    ) -> ScoreResult:
        """Return one explainable score result for the candidate."""

        feature_set = self.build_feature_set(candidate, snapshot)
        group_scores = self.calculate_group_scores(feature_set)
        normalized_score = self.combine_group_scores(group_scores)

        return ScoreResult(
            score_id=f"score:{candidate.candidate_id}:{self.name}",
            instrument_id=candidate.instrument_id,
            timestamp=snapshot.timestamp,
            model_name=self.name,
            model_version=self.version,
            score_value=normalized_score,
            rank=0,
            feature_set_name=feature_set.feature_set_name,
            candidate_ref=candidate.candidate_id,
            score_reason_summary=self._score_reason_summary(group_scores),
        )

    def build_feature_set(
        self,
        candidate: CandidateSelectionResult,
        snapshot: MarketDataSnapshot,
    ) -> CoreFeatureSet:
        """Build the core feature set for one candidate."""

        recent_bars = tuple(self.recent_bars_provider(candidate.instrument_id, snapshot))
        return self.core_feature_set_builder.build(candidate, snapshot, recent_bars)

    def calculate_group_scores(self, feature_set: CoreFeatureSet) -> dict[str, Decimal]:
        """Return the normalized group scores for one feature set."""

        return {
            "price_momentum": self._price_momentum_score(feature_set),
            "volume_liquidity": self._volume_liquidity_score(feature_set),
            "breakout_position": self._breakout_position_score(feature_set),
            "trend_volatility": self._trend_volatility_score(feature_set),
            "market_context": self._market_context_score(feature_set),
        }

    def combine_group_scores(self, group_scores: dict[str, Decimal]) -> Decimal:
        """Combine per-group scores into one normalized score."""

        total_weight = sum(self.group_weights.values(), Decimal("0"))
        weighted_score = sum(
            (
                group_scores[group_name] * self.group_weights[group_name]
                for group_name in group_scores
            ),
            Decimal("0"),
        ) / total_weight
        return FeatureScoreMath.clamp(weighted_score, Decimal("0"), Decimal("1"))

    def _price_momentum_score(self, feature_set: CoreFeatureSet) -> Decimal:
        price_momentum = feature_set.price_momentum
        scores = (
            FeatureScoreMath.normalize_positive(
                price_momentum.short_return_rate,
                self.price_return_cap,
            ),
            FeatureScoreMath.normalize_positive(
                price_momentum.medium_return_rate,
                self.price_return_cap,
            ),
            FeatureScoreMath.normalize_positive(
                price_momentum.long_return_rate,
                self.price_return_cap,
            ),
            FeatureScoreMath.normalize_positive(price_momentum.gap_rate, self.gap_rate_cap),
        )
        return FeatureScoreMath.average(scores)

    def _volume_liquidity_score(self, feature_set: CoreFeatureSet) -> Decimal:
        volume_liquidity = feature_set.volume_liquidity
        scores = (
            FeatureScoreMath.normalize_ratio_to_target(
                volume_liquidity.volume_ratio_to_average,
                self.volume_ratio_target,
            ),
            FeatureScoreMath.normalize_ratio_to_target(
                volume_liquidity.trading_value_ratio_to_average,
                self.trading_value_ratio_target,
            ),
        )
        return FeatureScoreMath.average(scores)

    def _breakout_position_score(self, feature_set: CoreFeatureSet) -> Decimal:
        breakout_position = feature_set.breakout_position
        scores = (
            FeatureScoreMath.normalize_positive(
                breakout_position.distance_from_lookback_high,
                self.breakout_distance_cap,
            ),
            FeatureScoreMath.normalize_between(
                breakout_position.close_strength_ratio,
                self.close_strength_min,
                self.close_strength_target,
            ),
        )
        return FeatureScoreMath.average(scores)

    def _trend_volatility_score(self, feature_set: CoreFeatureSet) -> Decimal:
        trend_volatility = feature_set.trend_volatility
        scores = (
            FeatureScoreMath.normalize_positive(
                trend_volatility.distance_from_short_moving_average,
                self.trend_gap_cap,
            ),
            FeatureScoreMath.normalize_positive(
                trend_volatility.distance_from_long_moving_average,
                self.trend_gap_cap,
            ),
            FeatureScoreMath.normalize_inverse_ratio(
                trend_volatility.intraday_range_ratio,
                self.max_intraday_range_ratio,
            ),
            FeatureScoreMath.normalize_between(
                trend_volatility.rsi_value,
                self.rsi_neutral_floor,
                self.rsi_neutral_ceiling,
            ),
        )
        return FeatureScoreMath.average(scores)

    def _market_context_score(self, feature_set: CoreFeatureSet) -> Decimal:
        market_context = feature_set.market_context
        scores = (
            FeatureScoreMath.clamp(market_context.filter_pass_ratio, Decimal("0"), Decimal("1")),
            FeatureScoreMath.clamp(market_context.final_snapshot_score, Decimal("0"), Decimal("1")),
            FeatureScoreMath.normalize_positive(
                market_context.trend_alignment_ratio,
                self.trend_alignment_cap,
            ),
        )
        return FeatureScoreMath.average(scores)

    @staticmethod
    def _score_reason_summary(group_scores: dict[str, Decimal]) -> str:
        ordered_groups = (
            "price_momentum",
            "volume_liquidity",
            "breakout_position",
            "trend_volatility",
            "market_context",
        )
        return "; ".join(
            f"{group_name}={group_scores[group_name].quantize(Decimal('0.0001'))}"
            for group_name in ordered_groups
        )


class FeatureScoreMath:
    """Math helpers shared by deterministic score components."""

    @staticmethod
    def clamp(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
        return min(upper, max(lower, value))

    @staticmethod
    def average(values: Sequence[Decimal]) -> Decimal:
        if not values:
            return Decimal("0")
        return sum(values, Decimal("0")) / Decimal(len(values))

    @staticmethod
    def normalize_positive(value: Decimal, cap: Decimal) -> Decimal:
        if cap <= Decimal("0"):
            raise ValueError("cap must be positive.")
        return FeatureScoreMath.clamp(value / cap, Decimal("0"), Decimal("1"))

    @staticmethod
    def normalize_ratio_to_target(value: Decimal, target: Decimal) -> Decimal:
        if target <= Decimal("0"):
            raise ValueError("target must be positive.")
        return FeatureScoreMath.clamp(value / target, Decimal("0"), Decimal("1"))

    @staticmethod
    def normalize_between(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
        if upper <= lower:
            raise ValueError("upper must be greater than lower.")
        return FeatureScoreMath.clamp((value - lower) / (upper - lower), Decimal("0"), Decimal("1"))

    @staticmethod
    def normalize_inverse_ratio(value: Decimal, cap: Decimal) -> Decimal:
        if cap <= Decimal("0"):
            raise ValueError("cap must be positive.")
        return FeatureScoreMath.clamp(Decimal("1") - (value / cap), Decimal("0"), Decimal("1"))
