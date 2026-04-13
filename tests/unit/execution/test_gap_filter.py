"""Gap filter tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from stock_trading_bot.core.models import MarketDataSnapshot, OrderRequest
from stock_trading_bot.execution import GapFilterPolicy


def test_gap_filter_blocks_large_gap_up_buy_orders() -> None:
    policy = GapFilterPolicy(
        enabled=True,
        block_gap_up=True,
        max_gap_up_rate=Decimal("0.05"),
    )
    decision = policy.evaluate(
        _order_request(side="buy"),
        open_snapshot=_open_snapshot(open_price=Decimal("110")),
        previous_close=Decimal("100"),
    )

    assert decision.allowed is False
    assert decision.gap_rate == Decimal("0.1")
    assert "blocked_gap_up" in decision.reason


def test_gap_filter_does_not_block_sell_orders() -> None:
    policy = GapFilterPolicy(
        enabled=True,
        block_gap_up=True,
        max_gap_up_rate=Decimal("0.05"),
    )
    decision = policy.evaluate(
        _order_request(side="sell"),
        open_snapshot=_open_snapshot(open_price=Decimal("110")),
        previous_close=Decimal("100"),
    )

    assert decision.allowed is True
    assert decision.reason == "gap_filter_not_applicable"


def _order_request(*, side: str) -> OrderRequest:
    return OrderRequest(
        order_request_id=f"order:{side}",
        instrument_id="AAA",
        timestamp=datetime(2026, 4, 1, 9, 0, tzinfo=UTC),
        side=side,
        order_type="market",
        quantity=Decimal("1"),
        price=Decimal("100"),
        time_in_force="day",
        source_signal_id="signal:1",
        risk_check_ref="risk:1",
        broker_mode="backtest",
        request_reason="test",
    )


def _open_snapshot(*, open_price: Decimal) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        snapshot_id="snapshot:AAA:2026-04-01",
        instrument_id="AAA",
        timestamp=datetime(2026, 4, 1, 9, 0, tzinfo=UTC),
        open_price=open_price,
        high_price=open_price,
        low_price=open_price,
        close_price=open_price,
        volume=100000,
        trading_value=open_price * Decimal("100000"),
        change_rate=Decimal("0"),
        is_final=False,
        session_phase="NEXT_OPEN_EXECUTION",
    )
