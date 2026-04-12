"""Backtest application entrypoint and runtime builder."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from stock_trading_bot.adapters import HistoricalMarketDataFeed, SimulatedBroker
from stock_trading_bot.core.models import Instrument
from stock_trading_bot.execution import FillProcessor, OrderManager
from stock_trading_bot.infrastructure.config import ConfigManager
from stock_trading_bot.infrastructure.logging import EventLogger
from stock_trading_bot.infrastructure.persistence import TradeRepository
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


def build_backtest_runtime(
    *,
    project_root: Path | None = None,
    data_directory: Path | None = None,
    result_directory: Path | None = None,
    log_directory: Path | None = None,
    config_overrides: Mapping[str, Any] | None = None,
) -> ExecutionRuntime:
    """Build the backtest runtime from repository config files."""

    root = project_root or Path(__file__).resolve().parents[3]
    config_manager = ConfigManager(project_root=root)
    config_bundle = config_manager.load_backtest_config_bundle(overrides=config_overrides)
    base_config = config_bundle.base
    mode_config = config_bundle.mode
    strategy_config = config_bundle.strategy
    risk_config = config_bundle.risk
    costs_config = config_bundle.costs
    market_config = config_bundle.market
    start_date = date.fromisoformat(mode_config["backtest"]["start_date"])
    end_date = date.fromisoformat(mode_config["backtest"]["end_date"])
    runtime_mode = str(mode_config.get("mode", base_config["runtime"]["mode"]))
    run_label = _build_run_label(runtime_mode, start_date, end_date)

    resolved_data_directory = data_directory or (root / base_config["paths"]["data_root"])
    resolved_result_directory = (
        result_directory or (root / mode_config["backtest"]["result_path"])
    ) / run_label
    resolved_log_directory = (
        log_directory or (root / base_config["paths"]["log_dir"])
    ) / run_label
    instruments = _discover_instruments(resolved_data_directory, market_config)
    instrument_by_id = {instrument.instrument_id: instrument for instrument in instruments}

    market_data_feed = HistoricalMarketDataFeed(data_directory=resolved_data_directory)
    trading_dates = market_data_feed.trading_dates(
        instruments,
        start_date=start_date,
        end_date=end_date,
    )
    if not trading_dates:
        raise ValueError(
            "No historical trading dates found within the configured backtest range. "
            f"range=({start_date}, {end_date}), data_directory={resolved_data_directory}"
        )
    candidate_selector = CandidateSelector(
        filter_policy=DefaultFilterPolicy(
            min_trading_value=_to_decimal(base_config["universe"]["min_trading_value"]),
            min_volume=int(base_config["universe"]["min_volume"]),
            name=base_config["universe"]["filter_policy"],
        )
    )

    def recent_bars_provider(instrument_id: str, snapshot: object) -> tuple[Any, ...]:
        del snapshot
        return market_data_feed.load_enriched_bars(instrument_by_id[instrument_id])

    cost_profile = CostProfile(
        buy_commission_rate=_to_decimal(costs_config["buy_commission_rate"]),
        sell_commission_rate=_to_decimal(costs_config["sell_commission_rate"]),
        sell_tax_rate=_to_decimal(costs_config["sell_tax_rate"]),
        buy_slippage_rate=_to_decimal(costs_config["buy_slippage_rate"]),
        sell_slippage_rate=_to_decimal(costs_config["sell_slippage_rate"]),
    )
    allocation_policy = EqualWeightAllocationPolicy(
        max_position_ratio=_to_decimal(risk_config["risk_checks"]["max_position_ratio"]),
        lot_size=_to_decimal(market_config["order_rules"]["lot_size"]),
    )
    risk_checker = PreTradeRiskChecker(
        risk_policy_name=risk_config["name"],
        max_active_positions=int(risk_config["risk_checks"]["max_active_positions"]),
        max_position_ratio=_to_decimal(risk_config["risk_checks"]["max_position_ratio"]),
        max_single_order_ratio=_to_decimal(risk_config["risk_checks"]["max_single_order_ratio"]),
        block_duplicate_long_entry=bool(risk_config["risk_checks"]["block_duplicate_long_entry"]),
        min_available_cash_after_order=_to_decimal(
            risk_config["risk_checks"]["min_available_cash_after_order"]
        ),
        buy_commission_rate=cost_profile.buy_commission_rate,
        buy_slippage_rate=cost_profile.buy_slippage_rate,
        allocation_policy=allocation_policy,
    )

    position_book = PositionBook()
    account_state_store = AccountStateStore(
        build_initial_account_state(
            account_state_id="account:backtest:001",
            broker_mode=mode_config["broker_mode"],
            cash_balance=_to_decimal(mode_config["backtest"]["initial_cash_balance"]),
            max_position_limit=int(risk_config["risk_checks"]["max_active_positions"]),
            timestamp=datetime.combine(trading_dates[0], time.min, tzinfo=UTC),
        )
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
        broker_mode=mode_config["broker_mode"],
        order_type=strategy_config["execution"]["order_type"],
        time_in_force=strategy_config["execution"]["time_in_force"],
        lot_size=_to_decimal(market_config["order_rules"]["lot_size"]),
        default_partial_sell_fraction=_to_decimal(
            strategy_config["exit"]["first_take_profit_fraction"]
        ),
    )

    signal_factory = SignalFactory(strategy_name=strategy_config["name"])
    close_confirmation_engine = CloseConfirmationEngine(
        breakout_lookback_days=int(strategy_config["entry"]["breakout_lookback_days"]),
        volume_ratio_min=_to_decimal(strategy_config["entry"]["volume_ratio_min"]),
        volume_ratio_target=_to_decimal(strategy_config["entry"]["volume_ratio_target"]),
        close_strength_min=_to_decimal(strategy_config["entry"]["close_strength_min"]),
        close_must_hold_recent_high=bool(strategy_config["entry"]["close_must_hold_recent_high"]),
    )
    entry_strategy = BreakoutSwingEntryStrategy(
        recent_bars_provider=recent_bars_provider,
        close_confirmation_engine=close_confirmation_engine,
        signal_factory=signal_factory,
        name=strategy_config["name"],
        use_final_snapshot_only=bool(strategy_config["entry"]["use_final_snapshot_only"]),
    )
    exit_policy = ConservativeExitPolicy(
        recent_bars_provider=recent_bars_provider,
        signal_factory=signal_factory,
        has_partial_take_profit_provider=portfolio_coordinator.has_partial_take_profit,
        name="conservative_exit_policy",
        stop_loss_rate=_to_decimal(strategy_config["exit"]["stop_loss_rate"]),
        first_take_profit_rate=_to_decimal(strategy_config["exit"]["first_take_profit_rate"]),
        first_take_profit_fraction=_to_decimal(strategy_config["exit"]["first_take_profit_fraction"]),
        remainder_exit_ma_window=5,
        use_final_snapshot_only=bool(strategy_config["entry"]["use_final_snapshot_only"]),
    )

    strategy_coordinator = StrategyCoordinator(
        instruments=instruments,
        market_data_feed=market_data_feed,
        candidate_selector=candidate_selector,
        entry_strategy=entry_strategy,
        exit_policy=exit_policy,
    )
    result_collector = ResultCollector()
    event_logger = EventLogger(
        log_directory=resolved_log_directory,
        record_order_requests=bool(base_config["logging"]["record_order_requests"]),
        record_order_state_changes=bool(base_config["logging"]["record_order_state_changes"]),
        record_fill_events=bool(base_config["logging"]["record_fill_events"]),
        record_position_changes=bool(base_config["logging"]["record_position_changes"]),
        record_pnl=bool(base_config["logging"]["record_pnl"]),
    )
    trade_repository = (
        TradeRepository(result_directory=resolved_result_directory)
        if bool(mode_config["backtest"]["persist_results"])
        else None
    )
    order_manager = OrderManager(broker=SimulatedBroker())
    execution_coordinator = ExecutionCoordinator(
        order_manager=order_manager,
        fill_processor=FillProcessor(order_manager=order_manager),
        portfolio_coordinator=portfolio_coordinator,
        result_collector=result_collector,
        event_logger=event_logger,
    )
    session_clock = SessionClock(
        start_date=start_date,
        end_date=end_date,
        session_phases=tuple(base_config["runtime"]["session_phases"]),
        trading_dates=trading_dates,
    )

    return ExecutionRuntime(
        session_clock=session_clock,
        strategy_coordinator=strategy_coordinator,
        execution_coordinator=execution_coordinator,
        portfolio_coordinator=portfolio_coordinator,
        result_collector=result_collector,
        event_logger=event_logger,
        trade_repository=trade_repository,
    )


def run_backtest(
    *,
    project_root: Path | None = None,
    data_directory: Path | None = None,
    result_directory: Path | None = None,
    log_directory: Path | None = None,
    config_overrides: Mapping[str, Any] | None = None,
):
    """Build the runtime and execute the configured backtest."""

    runtime = build_backtest_runtime(
        project_root=project_root,
        data_directory=data_directory,
        result_directory=result_directory,
        log_directory=log_directory,
        config_overrides=config_overrides,
    )
    return runtime.run_session()


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for the backtest runtime."""

    parser = argparse.ArgumentParser(description="Run the stock trading bot backtest runtime.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Repository root containing configs/ and data/.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Historical CSV directory. Defaults to configs/base.yaml paths.data_root.",
    )
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=None,
        help="Directory where persisted backtest artifacts are written.",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Directory where structured event logs are written.",
    )
    args = parser.parse_args(argv)

    result = run_backtest(
        project_root=args.project_root,
        data_directory=args.data_dir,
        result_directory=args.result_dir,
        log_directory=args.log_dir,
    )
    summary = result.summary
    print("Backtest completed.")
    print(f"phases={len(result.phase_history)}")
    print(f"candidates={len(result.candidates)}")
    print(f"signals={len(result.signals)}")
    print(f"orders={summary.order_request_count}")
    print(f"fill_events={summary.fill_event_count}")
    print(f"initial_equity={summary.initial_equity}")
    print(f"final_equity={summary.final_equity}")
    print(f"total_pnl={summary.total_pnl}")
    print(f"realized_pnl={summary.realized_pnl}")
    print(f"unrealized_pnl={summary.unrealized_pnl}")
    print(f"return_rate={summary.return_rate}")
    print(f"buy_commission={summary.accumulated_buy_commission}")
    print(f"sell_commission={summary.accumulated_sell_commission}")
    print(f"sell_tax={summary.accumulated_sell_tax}")
    print(f"slippage_estimate={summary.accumulated_slippage_cost_estimate}")
    print(f"active_positions={summary.active_position_count}")
    print(f"closed_positions={summary.closed_position_count}")
    return 0


def _discover_instruments(
    data_directory: Path,
    market_config: dict[str, Any],
) -> tuple[Instrument, ...]:
    if not data_directory.exists():
        raise FileNotFoundError(f"Historical data directory does not exist: {data_directory}")

    csv_paths = sorted(data_directory.glob("*.csv"))
    if not csv_paths:
        raise FileNotFoundError(f"No CSV files found in {data_directory}")

    market_name = str(market_config.get("name", "kr_stock"))
    return tuple(
        Instrument(
            instrument_id=csv_path.stem,
            symbol=csv_path.stem,
            name=csv_path.stem,
            market=market_name,
            asset_type="equity",
            sector="unknown",
            is_etf=False,
            is_active=True,
        )
        for csv_path in csv_paths
    )


def _to_decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _build_run_label(runtime_mode: str, start_date: date, end_date: date) -> str:
    return f"{runtime_mode}_{start_date.isoformat()}_{end_date.isoformat()}"


if __name__ == "__main__":
    raise SystemExit(main())
