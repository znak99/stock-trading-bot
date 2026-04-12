"""Top-level runtime orchestration for backtest session execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from stock_trading_bot.runtime.execution_coordinator import ExecutionCoordinator
from stock_trading_bot.runtime.portfolio_coordinator import PortfolioCoordinator
from stock_trading_bot.runtime.result_collector import ResultCollector, RuntimeResult
from stock_trading_bot.runtime.session_clock import SessionClock
from stock_trading_bot.runtime.strategy_coordinator import StrategyCoordinator


@dataclass(slots=True, kw_only=True)
class ExecutionRuntime:
    """Coordinate the session clock, strategy, execution, and portfolio layers."""

    session_clock: SessionClock
    strategy_coordinator: StrategyCoordinator
    execution_coordinator: ExecutionCoordinator
    portfolio_coordinator: PortfolioCoordinator
    result_collector: ResultCollector
    _bootstrapped: bool = field(default=False, init=False)

    def bootstrap(self) -> None:
        """Initialize runtime state before the session loop starts."""

        self.result_collector.record_initial_equity(
            self.portfolio_coordinator.current_account_state().total_equity
        )
        self._bootstrapped = True

    def run_session(self) -> RuntimeResult:
        """Execute the configured backtest session loop."""

        if not self._bootstrapped:
            self.bootstrap()

        for session_step in self.session_clock.iter_session_steps():
            self.result_collector.record_phase(session_step.trading_date, session_step.phase)

            if session_step.phase == "PRE_MARKET":
                self.run_pre_market(session_step.trading_date)
            elif session_step.phase == "NEXT_OPEN_EXECUTION":
                self.run_next_open_execution(session_step.trading_date)
            elif session_step.phase == "INTRADAY_MONITOR":
                self.run_intraday_monitor(session_step.trading_date)
            elif session_step.phase == "MARKET_CLOSE_PROCESS":
                self.run_market_close_process(session_step.trading_date)

        return self.shutdown()

    def run_pre_market(self, trading_date: date) -> None:
        """Prepare account timing and reserved-order visibility for the trading day."""

        del trading_date
        # v1 keeps the pre-market step light: state and reservations are loaded in memory.

    def run_intraday_monitor(self, trading_date: date) -> None:
        """Run intraday candidate scanning and optional exit monitoring."""

        intraday_snapshots = self.strategy_coordinator.snapshots_for_date(
            trading_date,
            session_phase="INTRADAY_MONITOR",
            is_final=False,
        )
        if intraday_snapshots:
            self.portfolio_coordinator.mark_to_market(intraday_snapshots)

        intraday_candidates = self.strategy_coordinator.scan_intraday_candidates(trading_date)
        self.result_collector.record_candidates(intraday_candidates)

        intraday_exit_signals = self.strategy_coordinator.evaluate_exit_signals(
            trading_date,
            self.portfolio_coordinator.open_positions(),
            session_phase="INTRADAY_MONITOR",
            is_final=False,
        )
        self.result_collector.record_signals(intraday_exit_signals)

    def run_market_close_process(self, trading_date: date) -> None:
        """Run close confirmation, ranking, risk checks, and next-open scheduling."""

        close_snapshots = self.strategy_coordinator.snapshots_for_date(
            trading_date,
            session_phase="MARKET_CLOSE_PROCESS",
            is_final=True,
        )
        if close_snapshots:
            self.portfolio_coordinator.mark_to_market(close_snapshots)

        close_candidates = self.strategy_coordinator.select_close_candidates(trading_date)
        self.result_collector.record_candidates(close_candidates)

        close_entry_signals = self.strategy_coordinator.confirm_close_candidates(
            trading_date,
            candidates=close_candidates,
            snapshots_by_instrument_id=close_snapshots,
        )
        self.result_collector.record_signals(close_entry_signals)

        close_exit_signals = self.strategy_coordinator.evaluate_exit_signals(
            trading_date,
            self.portfolio_coordinator.open_positions(),
            session_phase="MARKET_CLOSE_PROCESS",
            is_final=True,
        )
        self.result_collector.record_signals(close_exit_signals)

        ranked_candidates = tuple(
            candidate
            for candidate in close_candidates
            if any(signal.candidate_ref == candidate.candidate_id for signal in close_entry_signals)
        )
        score_results = self.strategy_coordinator.rank_candidates(
            ranked_candidates,
            signals=close_entry_signals,
            snapshots_by_instrument_id=close_snapshots,
        )
        self.result_collector.record_scores(score_results)
        score_lookup = {
            score_result.candidate_ref: score_result
            for score_result in score_results
        }
        next_trading_date = self.session_clock.next_trading_date(trading_date)

        ranked_entry_signals = tuple(
            sorted(
                close_entry_signals,
                key=lambda signal: score_lookup[signal.candidate_ref].rank
                if signal.candidate_ref in score_lookup
                else 10**9,
            )
        )
        if next_trading_date is None:
            scheduled_order_requests = ()
        else:
            scheduled_order_requests = self.portfolio_coordinator.schedule_next_open_orders(
                (*close_exit_signals, *ranked_entry_signals),
                snapshots_by_instrument_id=close_snapshots,
                scores_by_candidate_ref=score_lookup,
                execution_date=next_trading_date,
            )
        self.result_collector.record_order_requests(scheduled_order_requests)

    def run_next_open_execution(self, trading_date: date) -> None:
        """Submit next-open orders for the trading date and process all fills/events."""

        scheduled_orders = self.portfolio_coordinator.pop_scheduled_orders(trading_date)
        if not scheduled_orders:
            return

        open_snapshots = self.strategy_coordinator.snapshots_for_date(
            trading_date,
            session_phase="NEXT_OPEN_EXECUTION",
            is_final=False,
        )
        prepared_orders = self.portfolio_coordinator.prepare_orders_for_execution(
            scheduled_orders,
            snapshots_by_instrument_id=open_snapshots,
        )
        self.execution_coordinator.submit_orders(
            prepared_orders,
            market_snapshots_by_instrument_id=open_snapshots,
        )

    def shutdown(self) -> RuntimeResult:
        """Finalize and return the collected runtime result."""

        return self.result_collector.build_result(
            final_account_state=self.portfolio_coordinator.current_account_state(),
            final_positions=self.portfolio_coordinator.current_positions(),
        )
