"""Score-weighted allocation policy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from stock_trading_bot.core.models import AccountState, ScoreResult


@dataclass(slots=True, kw_only=True)
class WeightedScoreAllocationPolicy:
    """Allocate more capital to higher-scoring candidates within risk bounds."""

    min_position_ratio: Decimal = Decimal("0.08")
    max_position_ratio: Decimal = Decimal("0.20")
    score_floor: Decimal = Decimal("0.45")
    score_ceiling: Decimal = Decimal("0.90")
    fallback_position_ratio: Decimal | None = None
    lot_size: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if self.min_position_ratio <= Decimal("0"):
            raise ValueError("min_position_ratio must be positive.")
        if self.max_position_ratio <= Decimal("0"):
            raise ValueError("max_position_ratio must be positive.")
        if self.min_position_ratio > self.max_position_ratio:
            raise ValueError("min_position_ratio must not exceed max_position_ratio.")
        if self.score_ceiling <= self.score_floor:
            raise ValueError("score_ceiling must be greater than score_floor.")
        if self.lot_size <= Decimal("0"):
            raise ValueError("lot_size must be positive.")
        if self.fallback_position_ratio is None:
            self.fallback_position_ratio = self.max_position_ratio
        if self.fallback_position_ratio <= Decimal("0"):
            raise ValueError("fallback_position_ratio must be positive.")

    def target_capital(
        self,
        account_state: AccountState,
        *,
        score_result: ScoreResult | None = None,
    ) -> Decimal:
        """Return a score-scaled capital budget for one position."""

        return account_state.total_equity * self.target_position_ratio(score_result=score_result)

    def target_position_ratio(
        self,
        *,
        score_result: ScoreResult | None = None,
    ) -> Decimal:
        """Return the score-weighted target ratio for a new position."""

        if score_result is None:
            return min(self.max_position_ratio, self.fallback_position_ratio)

        clamped_score = min(
            self.score_ceiling,
            max(self.score_floor, score_result.score_value),
        )
        normalized_score = (clamped_score - self.score_floor) / (
            self.score_ceiling - self.score_floor
        )
        return self.min_position_ratio + (
            (self.max_position_ratio - self.min_position_ratio) * normalized_score
        )

    def quantity_for_capital(self, unit_price: Decimal, capital_budget: Decimal) -> Decimal:
        """Return the largest lot-aligned quantity within the capital budget."""

        if unit_price <= Decimal("0") or capital_budget <= Decimal("0"):
            return Decimal("0")

        raw_quantity = capital_budget / unit_price
        lot_count = (raw_quantity / self.lot_size).to_integral_value(rounding=ROUND_DOWN)
        quantity = lot_count * self.lot_size
        return max(quantity, Decimal("0"))
