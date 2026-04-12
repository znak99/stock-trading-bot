"""Structured event logging for reproducible backtest analysis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from stock_trading_bot.core.models import (
    AccountState,
    CandidateSelectionResult,
    OrderRequest,
    Position,
    ScoreResult,
    Signal,
)
from stock_trading_bot.execution import ProcessedOrderEvent
from stock_trading_bot.infrastructure._serialization import append_jsonl
from stock_trading_bot.universe.policies import CandidateFilterLogEntry

if TYPE_CHECKING:
    from stock_trading_bot.runtime.result_collector import BacktestSummary

FILL_EVENT_TYPES = frozenset({"partial_fill", "full_fill", "late_fill_after_cancel_request"})


@dataclass(slots=True, kw_only=True)
class EventLogger:
    """Write structured runtime events to a deterministic JSONL stream."""

    log_directory: Path
    record_order_requests: bool = True
    record_order_state_changes: bool = True
    record_fill_events: bool = True
    record_position_changes: bool = True
    record_pnl: bool = True
    _sequence: int = field(default=0, init=False)
    _event_log_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.log_directory.mkdir(parents=True, exist_ok=True)
        self._event_log_path = self.log_directory / "events.jsonl"
        self._event_log_path.write_text("", encoding="utf-8")

    @property
    def event_log_path(self) -> Path:
        """Return the backing JSONL path."""

        return self._event_log_path

    def log_session_phase(self, trading_date: date, phase: str) -> None:
        """Record one executed session phase."""

        self._write_record(
            "session_phase",
            {
                "trading_date": trading_date,
                "phase": phase,
            },
        )

    def log_filter_evaluations(
        self,
        filter_evaluations: Sequence[CandidateFilterLogEntry],
    ) -> None:
        """Record candidate filter evaluations."""

        for filter_evaluation in filter_evaluations:
            self._write_record("filter_evaluation", filter_evaluation)

    def log_candidates(self, candidates: Sequence[CandidateSelectionResult]) -> None:
        """Record candidate-selection outcomes."""

        for candidate in candidates:
            self._write_record("candidate_selection", candidate)

    def log_signals(self, signals: Sequence[Signal]) -> None:
        """Record generated strategy signals."""

        for signal in signals:
            self._write_record("signal", signal)

    def log_scores(self, scores: Sequence[ScoreResult]) -> None:
        """Record candidate ranking outcomes."""

        for score in scores:
            self._write_record("score_result", score)

    def log_order_requests(self, order_requests: Sequence[OrderRequest]) -> None:
        """Record created order requests."""

        if not self.record_order_requests:
            return

        for order_request in order_requests:
            self._write_record("order_request", order_request)

    def log_processed_order_event(self, processed_order_event: ProcessedOrderEvent) -> None:
        """Record one processed order event."""

        if self.record_order_state_changes:
            self._write_record("order_state_change", processed_order_event)

        if (
            self.record_fill_events
            and processed_order_event.order_event.event_type in FILL_EVENT_TYPES
        ):
            self._write_record("fill_event", processed_order_event)

    def log_portfolio_snapshot(
        self,
        *,
        processed_order_event: ProcessedOrderEvent,
        account_state: AccountState,
        positions: Sequence[Position],
    ) -> None:
        """Record portfolio snapshots after an execution event."""

        event_context = {
            "order_request_id": processed_order_event.order_event.order_request_id,
            "order_event_id": processed_order_event.order_event.order_event_id,
            "event_type": processed_order_event.order_event.event_type,
            "previous_state": processed_order_event.previous_state,
            "new_state": processed_order_event.new_state,
        }

        if (
            self.record_position_changes
            and processed_order_event.order_event.event_type in FILL_EVENT_TYPES
        ):
            self._write_record(
                "position_snapshot",
                {
                    "event_context": event_context,
                    "positions": tuple(positions),
                },
            )

        if self.record_pnl:
            self._write_record(
                "pnl_snapshot",
                {
                    "event_context": event_context,
                    "account_state": account_state,
                },
            )

    def log_account_state(self, account_state: AccountState, *, reason: str) -> None:
        """Record an account-state snapshot outside of order-event processing."""

        if not self.record_pnl:
            return

        self._write_record(
            "pnl_snapshot",
            {
                "reason": reason,
                "account_state": account_state,
            },
        )

    def log_summary(
        self,
        *,
        summary: BacktestSummary,
        final_account_state: AccountState,
        final_positions: Sequence[Position],
    ) -> None:
        """Record final backtest summary artifacts."""

        self._write_record("backtest_summary", summary)
        if self.record_pnl:
            self._write_record(
                "final_account_state",
                final_account_state,
            )
        if self.record_position_changes:
            self._write_record(
                "final_positions",
                {"positions": tuple(final_positions)},
            )

    def _write_record(self, record_type: str, payload: Any) -> None:
        self._sequence += 1
        append_jsonl(
            self._event_log_path,
            {
                "sequence": self._sequence,
                "record_type": record_type,
                "payload": payload,
            },
        )
