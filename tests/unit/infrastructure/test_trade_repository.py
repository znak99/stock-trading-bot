"""Trade repository persistence tests."""

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
from stock_trading_bot.infrastructure import TradeRepository
from stock_trading_bot.runtime.result_collector import (
    BacktestSummary,
    RuntimeResult,
    SessionPhaseRecord,
)


def test_trade_repository_persists_summary_manifest_and_fill_trade_records(tmp_path: Path) -> None:
    runtime_result = _build_runtime_result()
    repository = TradeRepository(result_directory=tmp_path / "results")

    saved_directory = repository.save_runtime_result(
        runtime_result,
        event_log_path=Path("C:/logs/backtest/events.jsonl"),
    )

    summary = _read_json(saved_directory / "summary.json")
    trade_records = _read_json(saved_directory / "trade_records.json")
    manifest = _read_json(saved_directory / "manifest.json")

    assert saved_directory == tmp_path / "results"
    assert (saved_directory / "runtime_result.json").exists()
    assert (saved_directory / "final_account_state.json").exists()
    assert (saved_directory / "final_positions.json").exists()
    assert summary["final_equity"] == "1001000"
    assert len(trade_records) == 1
    assert trade_records[0]["trade_sequence"] == 1
    assert trade_records[0]["side"] == "buy"
    assert trade_records[0]["gross_notional"] == "1000"
    assert manifest["event_log_path"] == "C:/logs/backtest/events.jsonl"


def _build_runtime_result() -> RuntimeResult:
    timestamp = datetime(2024, 1, 22, 9, 0, tzinfo=UTC)
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
    processed_order_event = ProcessedOrderEvent(
        order_event=OrderEvent(
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
        ),
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
        total_equity=Decimal("1001000"),
        cash_balance=Decimal("1000000"),
        available_cash=Decimal("1000000"),
        market_value=Decimal("1000"),
        active_position_count=1,
        max_position_limit=5,
        account_status="active",
        realized_pnl=Decimal("1000"),
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
    return RuntimeResult(
        phase_history=(SessionPhaseRecord(trading_date=date(2024, 1, 22), phase="PRE_MARKET"),),
        candidates=(candidate,),
        signals=(signal,),
        scores=(),
        order_requests=(order_request,),
        processed_order_events=(processed_order_event,),
        final_account_state=account_state,
        final_positions=(position,),
        summary=summary,
    )


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
