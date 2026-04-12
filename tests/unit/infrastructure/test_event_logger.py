"""Structured event logger tests."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from stock_trading_bot.core.enums import OrderState
from stock_trading_bot.core.models import (
    AccountState,
    CandidateSelectionResult,
    OrderEvent,
    OrderRequest,
    Position,
    Signal,
)
from stock_trading_bot.execution import ProcessedOrderEvent
from stock_trading_bot.infrastructure import EventLogger
from stock_trading_bot.runtime.result_collector import BacktestSummary
from stock_trading_bot.universe.policies import CandidateFilterLogEntry


def test_event_logger_records_required_categories_with_monotonic_sequences(
    tmp_path: Path,
) -> None:
    logger = EventLogger(log_directory=tmp_path / "logs")
    timestamp = datetime(2024, 1, 22, 15, 30, tzinfo=UTC)
    candidate = CandidateSelectionResult(
        candidate_id="candidate:005930:snapshot:1",
        instrument_id="005930",
        timestamp=timestamp,
        filter_policy_name="default_filter_policy",
        passed=True,
        passed_filters=("trading_status:trading_allowed",),
        failed_filters=(),
        eligibility_reason="passed_all_filters",
        market_snapshot_ref="snapshot:1",
    )
    signal = Signal(
        signal_id="signal:test",
        instrument_id="005930",
        timestamp=timestamp,
        signal_type="buy",
        strategy_name="breakout_swing_v1",
        signal_strength=Decimal("0.9"),
        decision_reason="breakout_confirmed",
        market_snapshot_ref="snapshot:1",
        candidate_ref=candidate.candidate_id,
        target_execution_time=timestamp,
        is_confirmed=True,
    )
    order_request = OrderRequest(
        order_request_id="order:test",
        instrument_id="005930",
        timestamp=timestamp,
        side="buy",
        order_type="market",
        quantity=Decimal("10"),
        price=Decimal("100"),
        time_in_force="day",
        source_signal_id=signal.signal_id,
        risk_check_ref="risk:test",
        broker_mode="backtest",
        request_reason="breakout_confirmed",
    )
    order_event = OrderEvent(
        order_event_id="event:test",
        order_request_id=order_request.order_request_id,
        timestamp=timestamp,
        event_type="full_fill",
        broker_order_id="broker:test",
        filled_quantity=Decimal("10"),
        filled_price_avg=Decimal("100"),
        remaining_quantity=Decimal("0"),
        event_message="filled",
        is_terminal=True,
    )
    processed_order_event = ProcessedOrderEvent(
        order_event=order_event,
        previous_state=OrderState.ACCEPTED,
        new_state=OrderState.FILLED,
    )
    position = Position(
        position_id="position:005930",
        instrument_id="005930",
        opened_at=timestamp,
        updated_at=timestamp,
        quantity=Decimal("10"),
        avg_entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        unrealized_pnl_rate=Decimal("0"),
        position_status="open",
        exit_policy_name="conservative_exit_policy",
    )
    account_state = AccountState(
        account_state_id="account:test",
        timestamp=timestamp,
        broker_mode="backtest",
        total_equity=Decimal("1000000"),
        cash_balance=Decimal("999000"),
        available_cash=Decimal("999000"),
        market_value=Decimal("1000"),
        active_position_count=1,
        max_position_limit=5,
        account_status="active",
        realized_pnl=Decimal("0"),
    )
    summary = BacktestSummary(
        initial_equity=Decimal("1000000"),
        final_equity=Decimal("1001000"),
        total_pnl=Decimal("1000"),
        realized_pnl=Decimal("1000"),
        unrealized_pnl=Decimal("0"),
        return_rate=Decimal("0.001"),
        accumulated_buy_commission=Decimal("10"),
        accumulated_sell_commission=Decimal("0"),
        accumulated_sell_tax=Decimal("0"),
        accumulated_slippage_cost_estimate=Decimal("3"),
        order_request_count=1,
        fill_event_count=1,
        buy_order_count=1,
        sell_order_count=0,
        active_position_count=1,
        closed_position_count=0,
    )

    logger.log_session_phase(date(2024, 1, 22), "PRE_MARKET")
    logger.log_filter_evaluations(
        (
            CandidateFilterLogEntry(
                candidate_id=candidate.candidate_id,
                instrument_id=candidate.instrument_id,
                timestamp=timestamp,
                filter_policy_name=candidate.filter_policy_name,
                market_snapshot_ref=candidate.market_snapshot_ref,
                filter_name="trading_status",
                passed=True,
                reason="trading_allowed",
            ),
        )
    )
    logger.log_candidates((candidate,))
    logger.log_signals((signal,))
    logger.log_order_requests((order_request,))
    logger.log_processed_order_event(processed_order_event)
    logger.log_portfolio_snapshot(
        processed_order_event=processed_order_event,
        account_state=account_state,
        positions=(position,),
    )
    logger.log_summary(
        summary=summary,
        final_account_state=account_state,
        final_positions=(position,),
    )

    records = _read_jsonl(logger.event_log_path)
    record_types = [record["record_type"] for record in records]

    assert [record["sequence"] for record in records] == list(range(1, len(records) + 1))
    assert {
        "session_phase",
        "filter_evaluation",
        "candidate_selection",
        "signal",
        "order_request",
        "order_state_change",
        "fill_event",
        "position_snapshot",
        "pnl_snapshot",
        "backtest_summary",
        "final_account_state",
        "final_positions",
    }.issubset(set(record_types))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]
