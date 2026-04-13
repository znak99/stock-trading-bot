"""Advanced deterministic ranking model with breakout-risk adjustments."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from stock_trading_bot.ai.basic_ranking_model import BasicRankingModel, FeatureScoreMath
from stock_trading_bot.ai.core_feature_set_builder import CoreFeatureSet
from stock_trading_bot.core.models import CandidateSelectionResult, MarketDataSnapshot, ScoreResult


@dataclass(slots=True, kw_only=True)
class AdvancedRankingModel:
    """Risk-adjusted candidate-ranking model for the step20 enhancement pass."""

    base_model: BasicRankingModel
    preferred_gap_rate: Decimal = Decimal("0.02")
    max_gap_penalty_rate: Decimal = Decimal("0.08")
    overbought_rsi_floor: Decimal = Decimal("78")
    overbought_rsi_ceiling: Decimal = Decimal("95")
    soft_intraday_range_ratio: Decimal = Decimal("0.05")
    hard_intraday_range_ratio: Decimal = Decimal("0.18")
    breakout_buffer_cap: Decimal = Decimal("0.03")
    volume_bonus_cap: Decimal = Decimal("0.75")
    breakout_bonus_weight: Decimal = Decimal("0.06")
    volume_bonus_weight: Decimal = Decimal("0.05")
    gap_penalty_weight: Decimal = Decimal("0.12")
    rsi_penalty_weight: Decimal = Decimal("0.08")
    volatility_penalty_weight: Decimal = Decimal("0.10")
    name: str = "advanced_ranking_model"
    version: str = "v2"
    def score_candidate(
        self,
        candidate: CandidateSelectionResult,
        snapshot: MarketDataSnapshot,
    ) -> ScoreResult:
        """Return one risk-adjusted score result for the candidate."""

        feature_set = self.base_model.build_feature_set(candidate, snapshot)
        group_scores = self.base_model.calculate_group_scores(feature_set)
        base_score = self.base_model.combine_group_scores(group_scores)

        adjustment_terms = self._calculate_adjustment_terms(feature_set)
        adjusted_score = FeatureScoreMath.clamp(
            base_score
            + adjustment_terms["breakout_bonus"]
            + adjustment_terms["volume_bonus"]
            - adjustment_terms["gap_penalty"]
            - adjustment_terms["rsi_penalty"]
            - adjustment_terms["volatility_penalty"],
            Decimal("0"),
            Decimal("1"),
        )

        return ScoreResult(
            score_id=f"score:{candidate.candidate_id}:{self.name}",
            instrument_id=candidate.instrument_id,
            timestamp=snapshot.timestamp,
            model_name=self.name,
            model_version=self.version,
            score_value=adjusted_score,
            rank=0,
            feature_set_name=feature_set.feature_set_name,
            candidate_ref=candidate.candidate_id,
            score_reason_summary=self._score_reason_summary(group_scores, adjustment_terms),
        )

    def _calculate_adjustment_terms(self, feature_set: CoreFeatureSet) -> dict[str, Decimal]:
        gap_rate = feature_set.price_momentum.gap_rate
        rsi_value = feature_set.trend_volatility.rsi_value
        intraday_range_ratio = feature_set.trend_volatility.intraday_range_ratio
        breakout_distance = feature_set.breakout_position.distance_from_lookback_high
        volume_ratio = feature_set.volume_liquidity.volume_ratio_to_average

        gap_penalty = FeatureScoreMath.normalize_positive(
            max(Decimal("0"), gap_rate - self.preferred_gap_rate),
            max(Decimal("0.0001"), self.max_gap_penalty_rate - self.preferred_gap_rate),
        ) * self.gap_penalty_weight
        rsi_penalty = FeatureScoreMath.normalize_positive(
            max(Decimal("0"), rsi_value - self.overbought_rsi_floor),
            max(Decimal("1"), self.overbought_rsi_ceiling - self.overbought_rsi_floor),
        ) * self.rsi_penalty_weight
        volatility_penalty = FeatureScoreMath.normalize_positive(
            max(Decimal("0"), intraday_range_ratio - self.soft_intraday_range_ratio),
            max(
                Decimal("0.0001"),
                self.hard_intraday_range_ratio - self.soft_intraday_range_ratio,
            ),
        ) * self.volatility_penalty_weight
        breakout_bonus = FeatureScoreMath.normalize_positive(
            max(Decimal("0"), breakout_distance),
            self.breakout_buffer_cap,
        ) * self.breakout_bonus_weight
        volume_bonus = FeatureScoreMath.normalize_positive(
            max(Decimal("0"), volume_ratio - Decimal("1")),
            self.volume_bonus_cap,
        ) * self.volume_bonus_weight

        return {
            "breakout_bonus": breakout_bonus,
            "volume_bonus": volume_bonus,
            "gap_penalty": gap_penalty,
            "rsi_penalty": rsi_penalty,
            "volatility_penalty": volatility_penalty,
        }

    @staticmethod
    def _score_reason_summary(
        group_scores: dict[str, Decimal],
        adjustment_terms: dict[str, Decimal],
    ) -> str:
        ordered_group_names = (
            "price_momentum",
            "volume_liquidity",
            "breakout_position",
            "trend_volatility",
            "market_context",
        )
        ordered_adjustment_names = (
            "breakout_bonus",
            "volume_bonus",
            "gap_penalty",
            "rsi_penalty",
            "volatility_penalty",
        )
        parts = [
            *(
                f"{group_name}={group_scores[group_name].quantize(Decimal('0.0001'))}"
                for group_name in ordered_group_names
            ),
            *(
                f"{adjustment_name}={adjustment_terms[adjustment_name].quantize(Decimal('0.0001'))}"
                for adjustment_name in ordered_adjustment_names
            ),
        ]
        return "; ".join(parts)
