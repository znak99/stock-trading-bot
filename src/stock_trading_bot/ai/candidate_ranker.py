"""Candidate ranking orchestration for AI scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from stock_trading_bot.core.interfaces import RankingModel
from stock_trading_bot.core.models import CandidateSelectionResult, MarketDataSnapshot, ScoreResult


@dataclass(slots=True, kw_only=True)
class CandidateRanker:
    """Apply a ranking model and normalize score ranks deterministically."""

    ranking_model: RankingModel

    def rank_candidates(
        self,
        candidates: Sequence[CandidateSelectionResult],
        *,
        snapshots_by_instrument_id: Mapping[str, MarketDataSnapshot],
    ) -> tuple[ScoreResult, ...]:
        """Score each candidate with snapshot data and return rank-normalized results."""

        raw_scores = tuple(
            self.ranking_model.score_candidate(
                candidate,
                snapshots_by_instrument_id[candidate.instrument_id],
            )
            for candidate in candidates
            if candidate.instrument_id in snapshots_by_instrument_id
        )
        return self.normalize_ranks(raw_scores)

    @staticmethod
    def normalize_ranks(raw_scores: Sequence[ScoreResult]) -> tuple[ScoreResult, ...]:
        """Sort score results and assign 1-based ranks."""

        ranked_scores = sorted(
            raw_scores,
            key=lambda score: (-score.score_value, score.instrument_id, score.score_id),
        )
        normalized_scores: list[ScoreResult] = []
        for index, score in enumerate(ranked_scores, start=1):
            normalized_scores.append(
                ScoreResult(
                    score_id=score.score_id,
                    instrument_id=score.instrument_id,
                    timestamp=score.timestamp,
                    model_name=score.model_name,
                    model_version=score.model_version,
                    score_value=score.score_value,
                    rank=index,
                    feature_set_name=score.feature_set_name,
                    candidate_ref=score.candidate_ref,
                    score_reason_summary=score.score_reason_summary,
                )
            )
        return tuple(normalized_scores)
