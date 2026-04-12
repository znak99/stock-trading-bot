"""Runtime result collection and summary objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from stock_trading_bot.core.models import (
    AccountState,
    CandidateSelectionResult,
    OrderRequest,
    Position,
    ScoreResult,
    Signal,
)
from stock_trading_bot.execution import ProcessedOrderEvent


@dataclass(slots=True, frozen=True, kw_only=True)
class SessionPhaseRecord:
    """Audit record for one executed session phase."""

    trading_date: date
    phase: str


@dataclass(slots=True, frozen=True, kw_only=True)
class RuntimeResult:
    """Collected runtime summary returned after a backtest session."""

    phase_history: tuple[SessionPhaseRecord, ...]
    candidates: tuple[CandidateSelectionResult, ...]
    signals: tuple[Signal, ...]
    scores: tuple[ScoreResult, ...]
    order_requests: tuple[OrderRequest, ...]
    processed_order_events: tuple[ProcessedOrderEvent, ...]
    final_account_state: AccountState
    final_positions: tuple[Position, ...]


@dataclass(slots=True, kw_only=True)
class ResultCollector:
    """Collect runtime artifacts for verification, debugging, and reporting."""

    phase_history: list[SessionPhaseRecord] = field(default_factory=list)
    candidates: list[CandidateSelectionResult] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    scores: list[ScoreResult] = field(default_factory=list)
    order_requests: list[OrderRequest] = field(default_factory=list)
    processed_order_events: list[ProcessedOrderEvent] = field(default_factory=list)

    def record_phase(self, trading_date: date, phase: str) -> None:
        """Record one executed phase."""

        self.phase_history.append(SessionPhaseRecord(trading_date=trading_date, phase=phase))

    def record_candidates(self, candidates: tuple[CandidateSelectionResult, ...]) -> None:
        """Append candidate-selection outcomes."""

        self.candidates.extend(candidates)

    def record_signals(self, signals: tuple[Signal, ...]) -> None:
        """Append strategy signals."""

        self.signals.extend(signals)

    def record_scores(self, scores: tuple[ScoreResult, ...]) -> None:
        """Append ranking results."""

        self.scores.extend(scores)

    def record_order_requests(self, order_requests: tuple[OrderRequest, ...]) -> None:
        """Append created order requests."""

        self.order_requests.extend(order_requests)

    def record_processed_order_event(self, processed_order_event: ProcessedOrderEvent) -> None:
        """Append one processed order event."""

        self.processed_order_events.append(processed_order_event)

    def build_result(
        self,
        *,
        final_account_state: AccountState,
        final_positions: tuple[Position, ...],
    ) -> RuntimeResult:
        """Build an immutable runtime result summary."""

        return RuntimeResult(
            phase_history=tuple(self.phase_history),
            candidates=tuple(self.candidates),
            signals=tuple(self.signals),
            scores=tuple(self.scores),
            order_requests=tuple(self.order_requests),
            processed_order_events=tuple(self.processed_order_events),
            final_account_state=final_account_state,
            final_positions=tuple(final_positions),
        )
