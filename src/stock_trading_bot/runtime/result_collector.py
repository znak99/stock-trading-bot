"""Runtime result collection and summary objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from stock_trading_bot.core.models import (
    AccountState,
    CandidateSelectionResult,
    OrderRequest,
    Position,
    ScoreResult,
    Signal,
)
from stock_trading_bot.execution import ProcessedOrderEvent

FILL_EVENT_TYPES = {"partial_fill", "full_fill", "late_fill_after_cancel_request"}


@dataclass(slots=True, frozen=True, kw_only=True)
class SessionPhaseRecord:
    """Audit record for one executed session phase."""

    trading_date: date
    phase: str


@dataclass(slots=True, frozen=True, kw_only=True)
class BacktestSummary:
    """High-level outcome metrics for one completed backtest session."""

    initial_equity: Decimal
    final_equity: Decimal
    total_pnl: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    return_rate: Decimal
    accumulated_buy_commission: Decimal
    accumulated_sell_commission: Decimal
    accumulated_sell_tax: Decimal
    accumulated_slippage_cost_estimate: Decimal
    order_request_count: int
    fill_event_count: int
    buy_order_count: int
    sell_order_count: int
    active_position_count: int
    closed_position_count: int


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
    summary: BacktestSummary


@dataclass(slots=True, kw_only=True)
class ResultCollector:
    """Collect runtime artifacts for verification, debugging, and reporting."""

    phase_history: list[SessionPhaseRecord] = field(default_factory=list)
    candidates: list[CandidateSelectionResult] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    scores: list[ScoreResult] = field(default_factory=list)
    order_requests: list[OrderRequest] = field(default_factory=list)
    processed_order_events: list[ProcessedOrderEvent] = field(default_factory=list)
    initial_equity: Decimal | None = None

    def record_initial_equity(self, equity: Decimal) -> None:
        """Capture the session's starting equity for result reporting."""

        if self.initial_equity is None:
            self.initial_equity = equity

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

        initial_equity = self.initial_equity or final_account_state.total_equity
        open_positions = tuple(
            position
            for position in final_positions
            if position.position_status == "open" and position.quantity > Decimal("0")
        )
        closed_positions = tuple(
            position
            for position in final_positions
            if position.position_status == "closed"
        )
        unrealized_pnl = sum(
            (position.unrealized_pnl for position in open_positions),
            start=Decimal("0"),
        )
        total_pnl = final_account_state.total_equity - initial_equity
        summary = BacktestSummary(
            initial_equity=initial_equity,
            final_equity=final_account_state.total_equity,
            total_pnl=total_pnl,
            realized_pnl=final_account_state.realized_pnl,
            unrealized_pnl=unrealized_pnl,
            return_rate=(
                Decimal("0")
                if initial_equity == Decimal("0")
                else total_pnl / initial_equity
            ),
            accumulated_buy_commission=final_account_state.accumulated_buy_commission,
            accumulated_sell_commission=final_account_state.accumulated_sell_commission,
            accumulated_sell_tax=final_account_state.accumulated_sell_tax,
            accumulated_slippage_cost_estimate=(
                final_account_state.accumulated_slippage_cost_estimate
            ),
            order_request_count=len(self.order_requests),
            fill_event_count=sum(
                1
                for processed_order_event in self.processed_order_events
                if processed_order_event.order_event.event_type in FILL_EVENT_TYPES
            ),
            buy_order_count=sum(
                1 for order_request in self.order_requests if order_request.side == "buy"
            ),
            sell_order_count=sum(
                1 for order_request in self.order_requests if order_request.side == "sell"
            ),
            active_position_count=len(open_positions),
            closed_position_count=len(closed_positions),
        )
        return RuntimeResult(
            phase_history=tuple(self.phase_history),
            candidates=tuple(self.candidates),
            signals=tuple(self.signals),
            scores=tuple(self.scores),
            order_requests=tuple(self.order_requests),
            processed_order_events=tuple(self.processed_order_events),
            final_account_state=final_account_state,
            final_positions=tuple(final_positions),
            summary=summary,
        )
