"""Universe candidate selection service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from stock_trading_bot.core.models import CandidateSelectionResult, Instrument, MarketDataSnapshot
from stock_trading_bot.universe.policies import (
    CandidateFilterLogEntry,
    FilterEvaluation,
    FilterPolicy,
)


class CandidateSelector:
    """Select eligible candidates from instrument snapshots using a filter policy."""

    def __init__(self, *, filter_policy: FilterPolicy) -> None:
        self._filter_policy = filter_policy
        self._evaluation_log: list[CandidateFilterLogEntry] = []

    @property
    def filter_policy_name(self) -> str:
        """Return the active filter policy name."""

        return self._filter_policy.name

    def select_candidate(
        self,
        instrument: Instrument,
        snapshot: MarketDataSnapshot,
    ) -> CandidateSelectionResult:
        """Evaluate a single candidate instrument."""

        outcome = self._filter_policy.evaluate(instrument, snapshot)
        candidate_id = self.build_candidate_id(instrument.instrument_id, snapshot.snapshot_id)
        self._append_log_entries(candidate_id, instrument, snapshot, outcome.evaluations)

        return CandidateSelectionResult(
            candidate_id=candidate_id,
            instrument_id=instrument.instrument_id,
            timestamp=snapshot.timestamp,
            filter_policy_name=self._filter_policy.name,
            passed=outcome.passed,
            passed_filters=outcome.passed_filters,
            failed_filters=outcome.failed_filters,
            eligibility_reason=outcome.eligibility_reason,
            market_snapshot_ref=snapshot.snapshot_id,
        )

    def select_candidates(
        self,
        instruments: Sequence[Instrument],
        snapshots_by_instrument_id: Mapping[str, MarketDataSnapshot],
    ) -> tuple[CandidateSelectionResult, ...]:
        """Evaluate multiple candidates using a snapshot lookup keyed by instrument_id."""

        results: list[CandidateSelectionResult] = []
        for instrument in instruments:
            snapshot = snapshots_by_instrument_id.get(instrument.instrument_id)
            if snapshot is None:
                raise ValueError(
                    f"Snapshot is required for instrument_id={instrument.instrument_id!r}."
                )
            results.append(self.select_candidate(instrument, snapshot))

        return tuple(results)

    def get_evaluation_log(self) -> tuple[CandidateFilterLogEntry, ...]:
        """Return the accumulated filter evaluation log."""

        return tuple(self._evaluation_log)

    def clear_evaluation_log(self) -> None:
        """Reset the accumulated filter evaluation log."""

        self._evaluation_log.clear()

    @staticmethod
    def build_candidate_id(instrument_id: str, snapshot_id: str) -> str:
        """Return a deterministic candidate identifier."""

        return f"candidate:{instrument_id}:{snapshot_id}"

    def _append_log_entries(
        self,
        candidate_id: str,
        instrument: Instrument,
        snapshot: MarketDataSnapshot,
        evaluations: Sequence[FilterEvaluation],
    ) -> None:
        for evaluation in evaluations:
            self._evaluation_log.append(
                CandidateFilterLogEntry(
                    candidate_id=candidate_id,
                    instrument_id=instrument.instrument_id,
                    timestamp=snapshot.timestamp,
                    filter_policy_name=self._filter_policy.name,
                    market_snapshot_ref=snapshot.snapshot_id,
                    filter_name=evaluation.filter_name,
                    passed=evaluation.passed,
                    reason=evaluation.reason,
                )
            )
