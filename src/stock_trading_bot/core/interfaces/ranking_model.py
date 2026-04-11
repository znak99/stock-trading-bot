"""Ranking model interface contract."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stock_trading_bot.core.models import (
    CandidateSelectionResult,
    MarketDataSnapshot,
    ScoreResult,
)


@runtime_checkable
class RankingModel(Protocol):
    """AI scoring contract for candidate ranking."""

    name: str
    version: str

    def score_candidate(
        self,
        candidate: CandidateSelectionResult,
        snapshot: MarketDataSnapshot,
    ) -> ScoreResult:
        """Generate a normalized score result for a candidate."""

