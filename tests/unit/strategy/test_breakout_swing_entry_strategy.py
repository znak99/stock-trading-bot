"""Tests for breakout swing entry strategy components."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from stock_trading_bot.core.models import CandidateSelectionResult, MarketDataSnapshot
from stock_trading_bot.market.services import HistoricalOhlcvBar
from stock_trading_bot.strategy import (
    BreakoutSwingEntryStrategy,
    CloseConfirmationEngine,
    SignalFactory,
)


def _build_candidate(*, passed: bool = True, snapshot_id: str = "snap-021") -> CandidateSelectionResult:
    return CandidateSelectionResult(
        candidate_id="cand-001",
        instrument_id="instr-001",
        timestamp=datetime(2026, 4, 21, 15, 30, tzinfo=UTC),
        filter_policy_name="default_filter_policy",
        passed=passed,
        passed_filters=("trading_status:trading_allowed",),
        failed_filters=(),
        eligibility_reason="passed_all_filters" if passed else "liquidity:volume_low",
        market_snapshot_ref=snapshot_id,
    )


def _build_snapshot(
    *,
    snapshot_id: str = "snap-021",
    close_price: str = "120",
    high_price: str = "121",
    volume: int = 2500,
    is_final: bool = True,
) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        snapshot_id=snapshot_id,
        instrument_id="instr-001",
        timestamp=datetime(2026, 4, 21, 15, 30, tzinfo=UTC),
        open_price=Decimal("110"),
        high_price=Decimal(high_price),
        low_price=Decimal("109"),
        close_price=Decimal(close_price),
        volume=volume,
        trading_value=Decimal(close_price) * Decimal(volume),
        change_rate=Decimal("0.04"),
        is_final=is_final,
        session_phase="MARKET_CLOSE_PROCESS" if is_final else "INTRADAY_MONITOR",
    )


def _build_recent_bars() -> tuple[HistoricalOhlcvBar, ...]:
    bars: list[HistoricalOhlcvBar] = []
    start = datetime(2026, 4, 1, 15, 30, tzinfo=UTC)
    for offset in range(20):
        close_price = Decimal("100") + Decimal(offset)
        bars.append(
            HistoricalOhlcvBar(
                instrument_id="instr-001",
                timestamp=start + timedelta(days=offset),
                open_price=close_price - Decimal("1"),
                high_price=close_price,
                low_price=close_price - Decimal("2"),
                close_price=close_price - Decimal("0.5"),
                volume=1000,
                trading_value=(close_price - Decimal("0.5")) * Decimal("1000"),
                change_rate=Decimal("0.01"),
            )
        )
    return tuple(bars)


def test_close_confirmation_engine_passes_when_breakout_conditions_hold() -> None:
    engine = CloseConfirmationEngine(
        breakout_lookback_days=20,
        volume_ratio_min=Decimal("1.5"),
        volume_ratio_target=Decimal("2.0"),
        close_strength_min=Decimal("0.8"),
    )

    result = engine.confirm(_build_snapshot(), _build_recent_bars())

    assert result.passed is True
    assert result.lookback_high == Decimal("119")
    assert result.average_volume == Decimal("1000")
    assert result.volume_ratio == Decimal("2.5")
    assert result.close_strength_ratio == Decimal("120") / Decimal("121")
    assert "close_above_recent_high(close=120,high=119)" in result.reasons


def test_breakout_swing_entry_strategy_creates_buy_signal_for_confirmed_breakout() -> None:
    strategy = BreakoutSwingEntryStrategy(
        recent_bars_provider=lambda instrument_id, snapshot: _build_recent_bars(),
        close_confirmation_engine=CloseConfirmationEngine(
            breakout_lookback_days=20,
            volume_ratio_min=Decimal("1.5"),
            volume_ratio_target=Decimal("2.0"),
            close_strength_min=Decimal("0.8"),
        ),
        signal_factory=SignalFactory(strategy_name="breakout_swing_v1"),
    )

    signal = strategy.evaluate_entry(_build_candidate(), _build_snapshot())

    assert signal is not None
    assert signal.signal_type == "buy"
    assert signal.strategy_name == "breakout_swing_v1"
    assert signal.market_snapshot_ref == "snap-021"
    assert signal.candidate_ref == "cand-001"
    assert signal.is_confirmed is True
    assert signal.target_execution_time == datetime(2026, 4, 22, 9, 0, tzinfo=UTC)
    assert signal.signal_strength > Decimal("0.9")


def test_breakout_swing_entry_strategy_returns_none_when_conditions_fail() -> None:
    strategy = BreakoutSwingEntryStrategy(
        recent_bars_provider=lambda instrument_id, snapshot: _build_recent_bars(),
        close_confirmation_engine=CloseConfirmationEngine(
            breakout_lookback_days=20,
            volume_ratio_min=Decimal("1.5"),
            volume_ratio_target=Decimal("2.0"),
            close_strength_min=Decimal("0.8"),
        ),
        signal_factory=SignalFactory(strategy_name="breakout_swing_v1"),
    )

    signal = strategy.evaluate_entry(
        _build_candidate(),
        _build_snapshot(close_price="118", high_price="125", volume=1200),
    )

    assert signal is None


def test_breakout_swing_entry_strategy_requires_confirmed_candidate_and_final_snapshot() -> None:
    strategy = BreakoutSwingEntryStrategy(
        recent_bars_provider=lambda instrument_id, snapshot: _build_recent_bars(),
        close_confirmation_engine=CloseConfirmationEngine(
            breakout_lookback_days=20,
            volume_ratio_min=Decimal("1.5"),
            volume_ratio_target=Decimal("2.0"),
            close_strength_min=Decimal("0.8"),
        ),
        signal_factory=SignalFactory(strategy_name="breakout_swing_v1"),
    )

    assert strategy.evaluate_entry(_build_candidate(passed=False), _build_snapshot()) is None
    assert strategy.evaluate_entry(_build_candidate(), _build_snapshot(is_final=False)) is None
