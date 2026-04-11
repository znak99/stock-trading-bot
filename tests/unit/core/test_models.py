"""Tests for shared core model contracts."""

from __future__ import annotations

from dataclasses import is_dataclass
from datetime import UTC, datetime
from decimal import Decimal

from stock_trading_bot.core.models import (
    AccountState,
    CandidateSelectionResult,
    Instrument,
    MarketDataSnapshot,
    OrderEvent,
    OrderRequest,
    Position,
    RiskCheckResult,
    ScoreResult,
    Signal,
)


def test_shared_models_follow_expected_contract_shape() -> None:
    timestamp = datetime(2026, 4, 12, 9, 0, tzinfo=UTC)

    instrument = Instrument(
        instrument_id="instr-001",
        symbol="005930",
        name="Samsung Electronics",
        market="KOSPI",
        asset_type="stock",
        sector="electronics",
        is_etf=False,
        is_active=True,
    )
    snapshot = MarketDataSnapshot(
        snapshot_id="snap-001",
        instrument_id=instrument.instrument_id,
        timestamp=timestamp,
        open_price=Decimal("70000"),
        high_price=Decimal("71000"),
        low_price=Decimal("69500"),
        close_price=Decimal("70800"),
        volume=1_250_000,
        trading_value=Decimal("88500000000"),
        change_rate=Decimal("0.012"),
        is_final=True,
        session_phase="MARKET_CLOSE_PROCESS",
    )
    candidate = CandidateSelectionResult(
        candidate_id="cand-001",
        instrument_id=instrument.instrument_id,
        timestamp=timestamp,
        filter_policy_name="default_filter_policy",
        passed=True,
        passed_filters=("liquidity", "price_range"),
        failed_filters=(),
        eligibility_reason="passed_all_filters",
        market_snapshot_ref=snapshot.snapshot_id,
    )
    signal = Signal(
        signal_id="sig-001",
        instrument_id=instrument.instrument_id,
        timestamp=timestamp,
        signal_type="buy",
        strategy_name="breakout_swing_v1",
        signal_strength=Decimal("0.85"),
        decision_reason="close breakout confirmed",
        market_snapshot_ref=snapshot.snapshot_id,
        candidate_ref=candidate.candidate_id,
        target_execution_time=timestamp,
        is_confirmed=True,
    )
    score = ScoreResult(
        score_id="score-001",
        instrument_id=instrument.instrument_id,
        timestamp=timestamp,
        model_name="basic_ranking_model",
        model_version="v1",
        score_value=Decimal("0.78"),
        rank=1,
        feature_set_name="CoreFeatureSet",
        candidate_ref=candidate.candidate_id,
        score_reason_summary="strong volume breakout",
    )
    risk_check = RiskCheckResult(
        risk_check_id="risk-001",
        timestamp=timestamp,
        instrument_id=instrument.instrument_id,
        order_request_preview={"order_type": "market", "quantity": "10"},
        risk_policy_name="conservative_risk_v1",
        passed=True,
        failure_reasons=(),
        allowed_quantity=Decimal("10"),
        allowed_capital=Decimal("708000"),
        account_state_ref="account-001",
        position_refs=(),
    )
    order_request = OrderRequest(
        order_request_id="req-001",
        instrument_id=instrument.instrument_id,
        timestamp=timestamp,
        side="buy",
        order_type="market",
        quantity=Decimal("10"),
        price=Decimal("70800"),
        time_in_force="day",
        source_signal_id=signal.signal_id,
        risk_check_ref=risk_check.risk_check_id,
        broker_mode="backtest",
        request_reason="confirmed entry signal",
    )
    order_event = OrderEvent(
        order_event_id="evt-001",
        order_request_id=order_request.order_request_id,
        timestamp=timestamp,
        event_type="broker_accepted",
        broker_order_id="broker-001",
        filled_quantity=Decimal("0"),
        filled_price_avg=Decimal("0"),
        remaining_quantity=Decimal("10"),
        event_message="accepted",
        is_terminal=False,
    )
    position = Position(
        position_id="pos-001",
        instrument_id=instrument.instrument_id,
        opened_at=timestamp,
        updated_at=timestamp,
        quantity=Decimal("10"),
        avg_entry_price=Decimal("70800"),
        current_price=Decimal("70800"),
        unrealized_pnl=Decimal("0"),
        unrealized_pnl_rate=Decimal("0"),
        position_status="open",
        exit_policy_name="conservative_exit_policy",
    )
    account_state = AccountState(
        account_state_id="account-001",
        timestamp=timestamp,
        broker_mode="backtest",
        total_equity=Decimal("10000000"),
        cash_balance=Decimal("9292000"),
        available_cash=Decimal("9292000"),
        market_value=Decimal("708000"),
        active_position_count=1,
        max_position_limit=5,
        account_status="active",
    )

    assert all(
        is_dataclass(model)
        for model in (
            instrument,
            snapshot,
            candidate,
            signal,
            score,
            risk_check,
            order_request,
            order_event,
            position,
            account_state,
        )
    )
    assert candidate.market_snapshot_ref == snapshot.snapshot_id
    assert signal.candidate_ref == candidate.candidate_id
    assert order_request.risk_check_ref == risk_check.risk_check_id
    assert order_event.order_request_id == order_request.order_request_id
    assert position.position_status == "open"
    assert account_state.reserved_cash == Decimal("0")
    assert account_state.reserved_sell_quantity == {}
