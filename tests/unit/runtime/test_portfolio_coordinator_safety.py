"""Portfolio coordinator safety behavior tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from stock_trading_bot.core.models import MarketDataSnapshot, Signal
from stock_trading_bot.portfolio import (
    AccountStateStore,
    EqualWeightAllocationPolicy,
    PortfolioUpdater,
    PositionBook,
    PreTradeRiskChecker,
)
from stock_trading_bot.portfolio.services.portfolio_updater import build_initial_account_state
from stock_trading_bot.runtime import PortfolioCoordinator


def test_portfolio_coordinator_blocks_duplicate_active_orders_and_releases_them() -> None:
    account_state_store = AccountStateStore(
        build_initial_account_state(
            account_state_id="account-portfolio-safety",
            broker_mode="backtest",
            cash_balance=Decimal("1000000"),
            max_position_limit=5,
            timestamp=datetime(2026, 4, 13, 9, 0, tzinfo=UTC),
        )
    )
    position_book = PositionBook()
    allocation_policy = EqualWeightAllocationPolicy(max_position_ratio=Decimal("0.20"))
    coordinator = PortfolioCoordinator(
        position_book=position_book,
        account_state_store=account_state_store,
        risk_checker=PreTradeRiskChecker(allocation_policy=allocation_policy),
        portfolio_updater=PortfolioUpdater(
            position_book=position_book,
            account_state_store=account_state_store,
        ),
        allocation_policy=allocation_policy,
        broker_mode="backtest",
        block_duplicate_active_orders=True,
    )
    snapshot = MarketDataSnapshot(
        snapshot_id="snapshot:BUY:20260413",
        instrument_id="BUY",
        timestamp=datetime(2026, 4, 13, 15, 20, tzinfo=UTC),
        open_price=Decimal("100"),
        high_price=Decimal("105"),
        low_price=Decimal("99"),
        close_price=Decimal("104"),
        volume=100000,
        trading_value=Decimal("10400000"),
        change_rate=Decimal("0.04"),
        is_final=True,
        session_phase="MARKET_CLOSE_PROCESS",
    )

    first_order_requests = coordinator.schedule_next_open_orders(
        (_build_buy_signal(signal_id="signal:buy:1"),),
        snapshots_by_instrument_id={"BUY": snapshot},
        execution_date=date(2026, 4, 14),
    )
    second_order_requests = coordinator.schedule_next_open_orders(
        (_build_buy_signal(signal_id="signal:buy:2"),),
        snapshots_by_instrument_id={"BUY": snapshot},
        execution_date=date(2026, 4, 14),
    )

    assert len(first_order_requests) == 1
    assert second_order_requests == ()
    assert coordinator.has_active_order("BUY", "buy") is True

    coordinator.release_order_request(first_order_requests[0].order_request_id)

    third_order_requests = coordinator.schedule_next_open_orders(
        (_build_buy_signal(signal_id="signal:buy:3"),),
        snapshots_by_instrument_id={"BUY": snapshot},
        execution_date=date(2026, 4, 14),
    )

    assert len(third_order_requests) == 1
    assert coordinator.has_active_order("BUY", "buy") is True


def _build_buy_signal(*, signal_id: str) -> Signal:
    return Signal(
        signal_id=signal_id,
        instrument_id="BUY",
        timestamp=datetime(2026, 4, 13, 15, 20, tzinfo=UTC),
        signal_type="buy",
        strategy_name="breakout_swing_v1",
        signal_strength=Decimal("0.9"),
        decision_reason="breakout_confirmed",
        market_snapshot_ref="snapshot:BUY:20260413",
        candidate_ref=f"candidate:{signal_id}",
        target_execution_time=datetime(2026, 4, 14, 9, 0, tzinfo=UTC),
        is_confirmed=True,
    )
