"""Runtime orchestration tests."""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from stock_trading_bot.adapters import HistoricalMarketDataFeed, SimulatedBroker
from stock_trading_bot.core.models import Instrument
from stock_trading_bot.execution import FillProcessor, OrderManager
from stock_trading_bot.portfolio import (
    AccountStateStore,
    CostProfile,
    EqualWeightAllocationPolicy,
    PortfolioUpdater,
    PositionBook,
    PreTradeRiskChecker,
)
from stock_trading_bot.portfolio.services.portfolio_updater import build_initial_account_state
from stock_trading_bot.runtime import (
    ExecutionCoordinator,
    ExecutionRuntime,
    PortfolioCoordinator,
    ResultCollector,
    SessionClock,
    StrategyCoordinator,
)
from stock_trading_bot.strategy import (
    BreakoutSwingEntryStrategy,
    CloseConfirmationEngine,
    ConservativeExitPolicy,
    SignalFactory,
)
from stock_trading_bot.universe import CandidateSelector, DefaultFilterPolicy


def test_session_clock_normalizes_aliases_and_uses_runtime_order() -> None:
    session_clock = SessionClock(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 2),
        session_phases=("PRE_MARKET", "INTRADAY", "CLOSE", "NEXT_OPEN"),
    )
    steps = tuple(session_clock.iter_session_steps())

    assert session_clock.session_phases == (
        "PRE_MARKET",
        "INTRADAY_MONITOR",
        "MARKET_CLOSE_PROCESS",
        "NEXT_OPEN_EXECUTION",
    )
    assert [step.phase for step in steps[:4]] == [
        "PRE_MARKET",
        "NEXT_OPEN_EXECUTION",
        "INTRADAY_MONITOR",
        "MARKET_CLOSE_PROCESS",
    ]
    assert len(steps) == 8


def test_execution_runtime_connects_close_signal_to_next_open_fill(tmp_path: Path) -> None:
    instrument = Instrument(
        instrument_id="005930",
        symbol="005930",
        name="Samsung Electronics",
        market="kr_stock",
        asset_type="equity",
        sector="technology",
        is_etf=False,
        is_active=True,
    )
    _write_runtime_fixture(tmp_path / "005930.csv")

    market_data_feed = HistoricalMarketDataFeed(data_directory=tmp_path)
    candidate_selector = CandidateSelector(
        filter_policy=DefaultFilterPolicy(
            min_trading_value=Decimal("100000"),
            min_volume=500,
        )
    )

    signal_factory = SignalFactory(strategy_name="breakout_swing_v1")
    close_confirmation_engine = CloseConfirmationEngine(
        breakout_lookback_days=20,
        volume_ratio_min=Decimal("1.5"),
        volume_ratio_target=Decimal("2.0"),
        close_strength_min=Decimal("0.8"),
    )

    def recent_bars_provider(instrument_id: str, snapshot: object):
        del snapshot
        assert instrument_id == "005930"
        return market_data_feed.load_enriched_bars(instrument)

    position_book = PositionBook()
    account_state_store = AccountStateStore(
        build_initial_account_state(
            account_state_id="account-test-001",
            broker_mode="backtest",
            cash_balance=Decimal("1000000"),
            max_position_limit=5,
            timestamp=datetime(2026, 4, 1, 9, 0, tzinfo=UTC),
        )
    )
    cost_profile = CostProfile()
    allocation_policy = EqualWeightAllocationPolicy(max_position_ratio=Decimal("0.20"))
    risk_checker = PreTradeRiskChecker(
        max_active_positions=5,
        max_position_ratio=Decimal("0.20"),
        max_single_order_ratio=Decimal("0.20"),
        allocation_policy=allocation_policy,
    )
    portfolio_updater = PortfolioUpdater(
        position_book=position_book,
        account_state_store=account_state_store,
        cost_profile=cost_profile,
    )
    portfolio_coordinator = PortfolioCoordinator(
        position_book=position_book,
        account_state_store=account_state_store,
        risk_checker=risk_checker,
        portfolio_updater=portfolio_updater,
        allocation_policy=allocation_policy,
        broker_mode="backtest",
        default_partial_sell_fraction=Decimal("0.5"),
    )

    entry_strategy = BreakoutSwingEntryStrategy(
        recent_bars_provider=recent_bars_provider,
        close_confirmation_engine=close_confirmation_engine,
        signal_factory=signal_factory,
    )
    exit_policy = ConservativeExitPolicy(
        recent_bars_provider=recent_bars_provider,
        signal_factory=signal_factory,
        has_partial_take_profit_provider=portfolio_coordinator.has_partial_take_profit,
    )
    strategy_coordinator = StrategyCoordinator(
        instruments=(instrument,),
        market_data_feed=market_data_feed,
        candidate_selector=candidate_selector,
        entry_strategy=entry_strategy,
        exit_policy=exit_policy,
    )
    result_collector = ResultCollector()
    order_manager = OrderManager(broker=SimulatedBroker())
    execution_coordinator = ExecutionCoordinator(
        order_manager=order_manager,
        fill_processor=FillProcessor(order_manager=order_manager),
        portfolio_coordinator=portfolio_coordinator,
        result_collector=result_collector,
    )
    runtime = ExecutionRuntime(
        session_clock=SessionClock(
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 22),
        ),
        strategy_coordinator=strategy_coordinator,
        execution_coordinator=execution_coordinator,
        portfolio_coordinator=portfolio_coordinator,
        result_collector=result_collector,
    )

    result = runtime.run_session()

    assert len(result.phase_history) == 22 * 4
    assert len(result.order_requests) == 1
    assert result.order_requests[0].timestamp == datetime(2026, 4, 22, 9, 0)
    assert any(signal.signal_type == "buy" for signal in result.signals)
    assert any(score.model_name == "signal_strength_fallback" for score in result.scores)
    assert [event.order_event.event_type for event in result.processed_order_events] == [
        "submit_enqueued",
        "submit_sent",
        "broker_accepted",
        "full_fill",
    ]
    assert result.final_account_state.active_position_count == 1
    assert result.final_account_state.cash_balance < Decimal("1000000")
    assert any(position.position_status == "open" for position in result.final_positions)
    open_position = next(
        position
        for position in result.final_positions
        if position.position_status == "open"
    )
    assert open_position.instrument_id == "005930"
    assert open_position.quantity > Decimal("0")


def _write_runtime_fixture(path: Path) -> None:
    fieldnames = ("date", "open", "high", "low", "close", "volume")
    rows: list[dict[str, str]] = []
    start_date = date(2026, 4, 1)

    for offset in range(20):
        base_price = Decimal("100") + Decimal(offset)
        rows.append(
            {
                "date": (start_date + timedelta(days=offset)).isoformat(),
                "open": str(base_price - Decimal("1")),
                "high": str(base_price),
                "low": str(base_price - Decimal("2")),
                "close": str(base_price - Decimal("0.5")),
                "volume": "1000",
            }
        )

    rows.append(
        {
            "date": date(2026, 4, 21).isoformat(),
            "open": "119",
            "high": "121",
            "low": "118",
            "close": "120",
            "volume": "2500",
        }
    )
    rows.append(
        {
            "date": date(2026, 4, 22).isoformat(),
            "open": "121",
            "high": "122",
            "low": "119",
            "close": "120.5",
            "volume": "1000",
        }
    )

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
