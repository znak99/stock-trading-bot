"""Default universe filter policy and filter-chain implementation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from stock_trading_bot.core.interfaces import Filter
from stock_trading_bot.core.models import Instrument, MarketDataSnapshot


@dataclass(slots=True, frozen=True, kw_only=True)
class FilterEvaluation:
    """Single filter evaluation outcome."""

    filter_name: str
    passed: bool
    reason: str


@dataclass(slots=True, frozen=True, kw_only=True)
class FilterChainResult:
    """Aggregated result for all filters evaluated for a candidate."""

    passed: bool
    evaluations: tuple[FilterEvaluation, ...]

    @property
    def passed_filters(self) -> tuple[str, ...]:
        """Return passed filter names and reasons."""

        return tuple(
            self._serialize_evaluation(evaluation)
            for evaluation in self.evaluations
            if evaluation.passed
        )

    @property
    def failed_filters(self) -> tuple[str, ...]:
        """Return failed filter names and reasons."""

        return tuple(
            self._serialize_evaluation(evaluation)
            for evaluation in self.evaluations
            if not evaluation.passed
        )

    @property
    def eligibility_reason(self) -> str:
        """Return the primary eligibility reason for the candidate."""

        if self.passed:
            return "passed_all_filters"

        first_failed_evaluation = next(
            evaluation for evaluation in self.evaluations if not evaluation.passed
        )
        return self._serialize_evaluation(first_failed_evaluation)

    @staticmethod
    def _serialize_evaluation(evaluation: FilterEvaluation) -> str:
        return f"{evaluation.filter_name}:{evaluation.reason}"


@dataclass(slots=True, frozen=True, kw_only=True)
class CandidateFilterLogEntry:
    """Structured audit record for a single filter evaluation."""

    candidate_id: str
    instrument_id: str
    timestamp: datetime
    filter_policy_name: str
    market_snapshot_ref: str
    filter_name: str
    passed: bool
    reason: str


class FilterChain:
    """Evaluate all configured filters and keep every outcome."""

    def __init__(self, filters: Sequence[Filter]) -> None:
        self._filters = tuple(filters)
        if not self._filters:
            raise ValueError("FilterChain requires at least one filter.")

    @property
    def filters(self) -> tuple[Filter, ...]:
        """Return configured filters."""

        return self._filters

    def evaluate(
        self,
        instrument: Instrument,
        snapshot: MarketDataSnapshot,
    ) -> FilterChainResult:
        """Evaluate every filter and return the aggregated outcome."""

        evaluations = tuple(
            self._evaluate_filter(market_filter, instrument, snapshot)
            for market_filter in self._filters
        )
        return FilterChainResult(
            passed=all(evaluation.passed for evaluation in evaluations),
            evaluations=evaluations,
        )

    @staticmethod
    def _evaluate_filter(
        market_filter: Filter,
        instrument: Instrument,
        snapshot: MarketDataSnapshot,
    ) -> FilterEvaluation:
        passed, reason = market_filter.evaluate(instrument, snapshot)
        return FilterEvaluation(
            filter_name=market_filter.name,
            passed=passed,
            reason=reason,
        )


@dataclass(slots=True, kw_only=True)
class FilterPolicy:
    """Named filter policy wrapping a filter chain."""

    name: str
    filter_chain: FilterChain

    def evaluate(
        self,
        instrument: Instrument,
        snapshot: MarketDataSnapshot,
    ) -> FilterChainResult:
        """Evaluate the policy against a candidate instrument and snapshot."""

        return self.filter_chain.evaluate(instrument, snapshot)


@dataclass(slots=True, frozen=True, kw_only=True)
class TradingStatusFilter:
    """Exclude halted or inactive instruments."""

    name: str = "trading_status"

    def evaluate(
        self,
        instrument: Instrument,
        snapshot: MarketDataSnapshot,
    ) -> tuple[bool, str]:
        del snapshot
        if instrument.is_active:
            return True, "trading_allowed"
        return False, "trading_halted_or_inactive"


@dataclass(slots=True, frozen=True, kw_only=True)
class TradingValueThresholdFilter:
    """Require a minimum daily trading value."""

    min_trading_value: Decimal
    name: str = "trading_value"

    def evaluate(
        self,
        instrument: Instrument,
        snapshot: MarketDataSnapshot,
    ) -> tuple[bool, str]:
        del instrument
        if snapshot.trading_value >= self.min_trading_value:
            return True, f"trading_value_gte_{self.min_trading_value}"
        return False, (
            f"trading_value_below_threshold(actual={snapshot.trading_value},"
            f"min={self.min_trading_value})"
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class LiquidityFilter:
    """Require a minimum executed volume for liquidity."""

    min_volume: int
    name: str = "liquidity"

    def evaluate(
        self,
        instrument: Instrument,
        snapshot: MarketDataSnapshot,
    ) -> tuple[bool, str]:
        del instrument
        if snapshot.volume >= self.min_volume:
            return True, f"volume_gte_{self.min_volume}"
        return False, f"volume_below_threshold(actual={snapshot.volume},min={self.min_volume})"


class DefaultFilterPolicy(FilterPolicy):
    """Standard universe filter policy used for initial backtests."""

    def __init__(
        self,
        *,
        min_trading_value: Decimal,
        min_volume: int,
        name: str = "default_filter_policy",
    ) -> None:
        if min_trading_value <= Decimal("0"):
            raise ValueError("min_trading_value must be positive.")
        if min_volume <= 0:
            raise ValueError("min_volume must be positive.")

        super().__init__(
            name=name,
            filter_chain=FilterChain(
                (
                    TradingStatusFilter(),
                    TradingValueThresholdFilter(min_trading_value=min_trading_value),
                    LiquidityFilter(min_volume=min_volume),
                )
            ),
        )
