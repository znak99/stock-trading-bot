"""Tests for the conservative exit policy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from stock_trading_bot.core.models import MarketDataSnapshot, Position
from stock_trading_bot.market.services import HistoricalOhlcvBar
from stock_trading_bot.strategy import ConservativeExitPolicy, SignalFactory


def _build_position(
    *,
    avg_entry_price: str = "100",
    current_price: str = "100",
    quantity: str = "10",
) -> Position:
    return Position(
        position_id="pos-001",
        instrument_id="instr-001",
        opened_at=datetime(2026, 4, 1, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 4, 21, 15, 30, tzinfo=UTC),
        quantity=Decimal(quantity),
        avg_entry_price=Decimal(avg_entry_price),
        current_price=Decimal(current_price),
        unrealized_pnl=Decimal("0"),
        unrealized_pnl_rate=Decimal("0"),
        position_status="open",
        exit_policy_name="conservative_exit_policy",
    )


def _build_snapshot(*, close_price: str, high_price: str | None = None, is_final: bool = True) -> MarketDataSnapshot:
    high = Decimal(high_price or close_price)
    return MarketDataSnapshot(
        snapshot_id="snap-001",
        instrument_id="instr-001",
        timestamp=datetime(2026, 4, 21, 15, 30, tzinfo=UTC),
        open_price=Decimal("100"),
        high_price=high,
        low_price=Decimal("95"),
        close_price=Decimal(close_price),
        volume=1000,
        trading_value=Decimal(close_price) * Decimal("1000"),
        change_rate=Decimal("0"),
        is_final=is_final,
        session_phase="MARKET_CLOSE_PROCESS" if is_final else "INTRADAY_MONITOR",
    )


def _build_recent_bars(*, closing_prices: tuple[str, ...]) -> tuple[HistoricalOhlcvBar, ...]:
    start = datetime(2026, 4, 16, 15, 30, tzinfo=UTC)
    bars: list[HistoricalOhlcvBar] = []
    for offset, close in enumerate(closing_prices):
        close_price = Decimal(close)
        bars.append(
            HistoricalOhlcvBar(
                instrument_id="instr-001",
                timestamp=start + timedelta(days=offset),
                open_price=close_price,
                high_price=close_price,
                low_price=close_price,
                close_price=close_price,
                volume=1000,
                trading_value=close_price * Decimal("1000"),
                change_rate=Decimal("0"),
            )
        )
    return tuple(bars)


def _build_policy(*, partial_taken: bool = False, recent_bars: tuple[HistoricalOhlcvBar, ...] | None = None) -> ConservativeExitPolicy:
    return ConservativeExitPolicy(
        recent_bars_provider=lambda instrument_id, snapshot: recent_bars or _build_recent_bars(
            closing_prices=("103", "104", "105", "106")
        ),
        signal_factory=SignalFactory(strategy_name="conservative_exit_policy"),
        has_partial_take_profit_provider=lambda position: partial_taken,
    )


def test_conservative_exit_policy_generates_full_sell_on_stop_loss() -> None:
    policy = _build_policy()

    signals = policy.evaluate(_build_position(), _build_snapshot(close_price="97.4"))

    assert len(signals) == 1
    assert signals[0].signal_type == "sell"
    assert "stop_loss_triggered" in signals[0].decision_reason
    assert signals[0].candidate_ref == "pos-001"


def test_conservative_exit_policy_generates_partial_sell_on_take_profit() -> None:
    policy = _build_policy()

    signals = policy.evaluate(_build_position(), _build_snapshot(close_price="103.6"))

    assert len(signals) == 1
    assert signals[0].signal_type == "partial_sell"
    assert "fraction=0.5" in signals[0].decision_reason
    assert signals[0].target_execution_time == datetime(2026, 4, 22, 9, 0, tzinfo=UTC)


def test_conservative_exit_policy_generates_full_sell_when_remaining_position_breaks_sma5() -> None:
    recent_bars = _build_recent_bars(closing_prices=("108", "107", "106", "105"))
    policy = _build_policy(partial_taken=True, recent_bars=recent_bars)

    signals = policy.evaluate(_build_position(), _build_snapshot(close_price="100"))

    assert len(signals) == 1
    assert signals[0].signal_type == "sell"
    assert "trend_exit_triggered" in signals[0].decision_reason


def test_conservative_exit_policy_returns_no_signal_without_exit_condition() -> None:
    policy = _build_policy(partial_taken=False)

    signals = policy.evaluate(_build_position(), _build_snapshot(close_price="101"))

    assert signals == ()
