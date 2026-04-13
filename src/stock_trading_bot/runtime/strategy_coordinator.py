"""Strategy orchestration across market data, filters, entry, exit, and ranking."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from stock_trading_bot.adapters import HistoricalMarketDataFeed
from stock_trading_bot.ai import CandidateRanker
from stock_trading_bot.core.interfaces import ExitPolicy, RankingModel, Strategy
from stock_trading_bot.core.models import (
    CandidateSelectionResult,
    Instrument,
    MarketDataSnapshot,
    Position,
    ScoreResult,
    Signal,
)
from stock_trading_bot.universe import CandidateSelector
from stock_trading_bot.universe.policies import CandidateFilterLogEntry


@dataclass(slots=True, kw_only=True)
class StrategyCoordinator:
    """Coordinate candidate scanning, signal generation, and candidate ranking."""

    instruments: tuple[Instrument, ...]
    market_data_feed: HistoricalMarketDataFeed
    candidate_selector: CandidateSelector
    entry_strategy: Strategy
    exit_policy: ExitPolicy
    ranking_model: RankingModel | None = None
    fallback_model_name: str = "signal_strength_fallback"
    fallback_model_version: str = "v1"

    def snapshots_for_date(
        self,
        trading_date: date,
        *,
        session_phase: str,
        is_final: bool,
    ) -> dict[str, MarketDataSnapshot]:
        """Return snapshots available for one trading date."""

        snapshots_by_instrument_id: dict[str, MarketDataSnapshot] = {}
        for instrument in self.instruments:
            for snapshot in self.market_data_feed.build_snapshots(
                instrument,
                session_phase=session_phase,
                is_final=is_final,
            ):
                if snapshot.timestamp.date() == trading_date:
                    snapshots_by_instrument_id[instrument.instrument_id] = snapshot
                    break
        return snapshots_by_instrument_id

    def previous_closes_for_date(self, trading_date: date) -> dict[str, Decimal]:
        """Return prior-session closes keyed by instrument_id for one trading date."""

        return {
            instrument.instrument_id: previous_close
            for instrument in self.instruments
            if (
                previous_close := self.market_data_feed.previous_close(
                    instrument,
                    trading_date=trading_date,
                )
            )
            is not None
        }

    def scan_intraday_candidates(self, trading_date: date) -> tuple[CandidateSelectionResult, ...]:
        """Run the intraday universe scan for a trading date."""

        return self._select_candidates(
            trading_date,
            session_phase="INTRADAY_MONITOR",
            is_final=False,
        )

    def select_close_candidates(self, trading_date: date) -> tuple[CandidateSelectionResult, ...]:
        """Run the close-based universe scan for a trading date."""

        return self._select_candidates(
            trading_date,
            session_phase="MARKET_CLOSE_PROCESS",
            is_final=True,
        )

    def confirm_close_candidates(
        self,
        trading_date: date,
        *,
        candidates: Sequence[CandidateSelectionResult] | None = None,
        snapshots_by_instrument_id: Mapping[str, MarketDataSnapshot] | None = None,
    ) -> tuple[Signal, ...]:
        """Create buy signals for close-confirmed breakout candidates."""

        close_snapshots = dict(
            snapshots_by_instrument_id
            or self.snapshots_for_date(
                trading_date,
                session_phase="MARKET_CLOSE_PROCESS",
                is_final=True,
            )
        )
        close_candidates = tuple(candidates or self.select_close_candidates(trading_date))

        signals: list[Signal] = []
        for candidate in close_candidates:
            snapshot = close_snapshots.get(candidate.instrument_id)
            if snapshot is None:
                continue
            signal = self.entry_strategy.evaluate_entry(candidate, snapshot)
            if signal is not None:
                signals.append(signal)
        return tuple(signals)

    def evaluate_exit_signals(
        self,
        trading_date: date,
        positions: Sequence[Position],
        *,
        session_phase: str,
        is_final: bool,
    ) -> tuple[Signal, ...]:
        """Evaluate exit signals for open positions using the requested phase snapshot."""

        snapshots_by_instrument_id = self.snapshots_for_date(
            trading_date,
            session_phase=session_phase,
            is_final=is_final,
        )
        signals: list[Signal] = []
        for position in positions:
            snapshot = snapshots_by_instrument_id.get(position.instrument_id)
            if snapshot is None:
                continue
            signals.extend(self.exit_policy.evaluate(position, snapshot))
        return tuple(signals)

    def rank_candidates(
        self,
        candidates: Sequence[CandidateSelectionResult],
        *,
        signals: Sequence[Signal],
        snapshots_by_instrument_id: Mapping[str, MarketDataSnapshot],
    ) -> tuple[ScoreResult, ...]:
        """Rank close-confirmed candidates with a model or rule-based fallback."""

        if self.ranking_model is not None:
            return CandidateRanker(ranking_model=self.ranking_model).rank_candidates(
                candidates,
                snapshots_by_instrument_id=snapshots_by_instrument_id,
            )

        signal_by_candidate_ref = {signal.candidate_ref: signal for signal in signals}
        fallback_scores = tuple(
            ScoreResult(
                score_id=f"score:{candidate.candidate_id}",
                instrument_id=candidate.instrument_id,
                timestamp=snapshots_by_instrument_id[candidate.instrument_id].timestamp,
                model_name=self.fallback_model_name,
                model_version=self.fallback_model_version,
                score_value=signal_by_candidate_ref[candidate.candidate_id].signal_strength,
                rank=0,
                feature_set_name="signal_strength",
                candidate_ref=candidate.candidate_id,
                score_reason_summary="ranked_by_signal_strength",
            )
            for candidate in candidates
            if candidate.candidate_id in signal_by_candidate_ref
            and candidate.instrument_id in snapshots_by_instrument_id
        )
        return CandidateRanker.normalize_ranks(fallback_scores)

    def drain_filter_evaluation_log(self) -> tuple[CandidateFilterLogEntry, ...]:
        """Return and clear accumulated filter-evaluation logs."""

        filter_evaluation_log = self.candidate_selector.get_evaluation_log()
        self.candidate_selector.clear_evaluation_log()
        return filter_evaluation_log

    def _select_candidates(
        self,
        trading_date: date,
        *,
        session_phase: str,
        is_final: bool,
    ) -> tuple[CandidateSelectionResult, ...]:
        snapshots_by_instrument_id = self.snapshots_for_date(
            trading_date,
            session_phase=session_phase,
            is_final=is_final,
        )
        eligible_instruments = tuple(
            instrument
            for instrument in self.instruments
            if instrument.instrument_id in snapshots_by_instrument_id
        )
        if not eligible_instruments:
            return ()
        return self.candidate_selector.select_candidates(
            eligible_instruments,
            snapshots_by_instrument_id,
        )

