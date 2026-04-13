"""Weighted allocation policy tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from stock_trading_bot.core.models import AccountState, ScoreResult
from stock_trading_bot.portfolio import WeightedScoreAllocationPolicy


def test_weighted_score_allocation_policy_scales_capital_by_score() -> None:
    policy = WeightedScoreAllocationPolicy(
        min_position_ratio=Decimal("0.08"),
        max_position_ratio=Decimal("0.20"),
        score_floor=Decimal("0.45"),
        score_ceiling=Decimal("0.90"),
        fallback_position_ratio=Decimal("0.20"),
    )
    account_state = _account_state(total_equity=Decimal("10000000"))

    low_capital = policy.target_capital(
        account_state,
        score_result=_score_result("low", Decimal("0.45")),
    )
    high_capital = policy.target_capital(
        account_state,
        score_result=_score_result("high", Decimal("0.90")),
    )

    assert low_capital == Decimal("800000.00")
    assert high_capital == Decimal("2000000.00")
    assert policy.quantity_for_capital(Decimal("50000"), low_capital) == Decimal("16")
    assert policy.quantity_for_capital(Decimal("50000"), high_capital) == Decimal("40")


def _account_state(*, total_equity: Decimal) -> AccountState:
    return AccountState(
        account_state_id="account:test",
        timestamp=datetime(2026, 4, 1, 9, 0, tzinfo=UTC),
        broker_mode="backtest",
        total_equity=total_equity,
        cash_balance=total_equity,
        available_cash=total_equity,
        market_value=Decimal("0"),
        active_position_count=0,
        max_position_limit=5,
        account_status="active",
        reserved_cash=Decimal("0"),
        reserved_sell_quantity={},
        realized_pnl=Decimal("0"),
        accumulated_buy_commission=Decimal("0"),
        accumulated_sell_commission=Decimal("0"),
        accumulated_sell_tax=Decimal("0"),
        accumulated_slippage_cost_estimate=Decimal("0"),
    )


def _score_result(score_id_suffix: str, score_value: Decimal) -> ScoreResult:
    return ScoreResult(
        score_id=f"score:{score_id_suffix}",
        instrument_id="AAA",
        timestamp=datetime(2026, 4, 1, 15, 30, tzinfo=UTC),
        model_name="advanced_ranking_model",
        model_version="v2",
        score_value=score_value,
        rank=1,
        feature_set_name="core_feature_set_v1",
        candidate_ref="candidate:AAA",
        score_reason_summary="test",
    )
