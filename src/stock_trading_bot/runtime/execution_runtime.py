"""Top-level runtime orchestration for backtest session execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from stock_trading_bot.execution import GapFilterPolicy
from stock_trading_bot.infrastructure.logging import EventLogger
from stock_trading_bot.infrastructure.notifications import AlertDispatcher, AlertNotification
from stock_trading_bot.infrastructure.persistence import TradeRepository
from stock_trading_bot.runtime.execution_coordinator import ExecutionCoordinator
from stock_trading_bot.runtime.operational_safety import OperationalSafetyGuard
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
    event_logger: EventLogger | None = None
    trade_repository: TradeRepository | None = None
    operational_safety_guard: OperationalSafetyGuard | None = None
    alert_dispatcher: AlertDispatcher | None = None
    gap_filter_policy: GapFilterPolicy | None = None
    _bootstrapped: bool = field(default=False, init=False)

    def bootstrap(self) -> None:
        """Initialize runtime state before the session loop starts."""

        self.result_collector.record_initial_equity(
            self.portfolio_coordinator.current_account_state().total_equity
        )
        if self.event_logger is not None:
            self.event_logger.log_account_state(
                self.portfolio_coordinator.current_account_state(),
                reason="bootstrap",
            )
        self._bootstrapped = True

    def run_session(self) -> RuntimeResult:
        """Execute the configured backtest session loop."""

        if not self._bootstrapped:
            self.bootstrap()

        for session_step in self.session_clock.iter_session_steps():
            self.result_collector.record_phase(session_step.trading_date, session_step.phase)
            if self.event_logger is not None:
                self.event_logger.log_session_phase(
                    session_step.trading_date,
                    session_step.phase,
                )

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

        if self.operational_safety_guard is not None:
            self.operational_safety_guard.start_trading_day(
                trading_date,
                self.portfolio_coordinator.current_account_state(),
            )
        self._evaluate_operational_safety(trading_date, reason="pre_market")

    def run_intraday_monitor(self, trading_date: date) -> None:
        """Run intraday candidate scanning and optional exit monitoring."""

        intraday_snapshots = self.strategy_coordinator.snapshots_for_date(
            trading_date,
            session_phase="INTRADAY_MONITOR",
            is_final=False,
        )
        if intraday_snapshots:
            self.portfolio_coordinator.mark_to_market(intraday_snapshots)
            self._evaluate_operational_safety(trading_date, reason="intraday_mark_to_market")

        intraday_candidates = self.strategy_coordinator.scan_intraday_candidates(trading_date)
        self._record_candidates(intraday_candidates)

        intraday_exit_signals = self.strategy_coordinator.evaluate_exit_signals(
            trading_date,
            self.portfolio_coordinator.open_positions(),
            session_phase="INTRADAY_MONITOR",
            is_final=False,
        )
        self._record_signals(intraday_exit_signals)

    def run_market_close_process(self, trading_date: date) -> None:
        """Run close confirmation, ranking, risk checks, and next-open scheduling."""

        close_snapshots = self.strategy_coordinator.snapshots_for_date(
            trading_date,
            session_phase="MARKET_CLOSE_PROCESS",
            is_final=True,
        )
        if close_snapshots:
            self.portfolio_coordinator.mark_to_market(close_snapshots)
            self._evaluate_operational_safety(trading_date, reason="close_mark_to_market")

        close_candidates = self.strategy_coordinator.select_close_candidates(trading_date)
        self._record_candidates(close_candidates)

        close_entry_signals = self.strategy_coordinator.confirm_close_candidates(
            trading_date,
            candidates=close_candidates,
            snapshots_by_instrument_id=close_snapshots,
        )
        self._record_signals(close_entry_signals)

        close_exit_signals = self.strategy_coordinator.evaluate_exit_signals(
            trading_date,
            self.portfolio_coordinator.open_positions(),
            session_phase="MARKET_CLOSE_PROCESS",
            is_final=True,
        )
        self._record_signals(close_exit_signals)
        close_entry_signals = self._filter_duplicate_signals(close_entry_signals)
        close_entry_signals, close_exit_signals = self._apply_order_block_policy(
            close_entry_signals=close_entry_signals,
            close_exit_signals=close_exit_signals,
        )

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
        self._record_scores(score_results)
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
        self._record_order_requests(scheduled_order_requests)

    def run_next_open_execution(self, trading_date: date) -> None:
        """Submit next-open orders for the trading date and process all fills/events."""

        scheduled_orders = self.portfolio_coordinator.pop_scheduled_orders(trading_date)
        if not scheduled_orders:
            return
        scheduled_orders = self._filter_blocked_order_requests(
            trading_date,
            scheduled_orders,
        )
        if not scheduled_orders:
            return

        open_snapshots = self.strategy_coordinator.snapshots_for_date(
            trading_date,
            session_phase="NEXT_OPEN_EXECUTION",
            is_final=False,
        )
        scheduled_orders = self._filter_gap_blocked_order_requests(
            trading_date,
            scheduled_orders,
            open_snapshots,
        )
        if not scheduled_orders:
            return
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

        runtime_result = self.result_collector.build_result(
            final_account_state=self.portfolio_coordinator.current_account_state(),
            final_positions=self.portfolio_coordinator.current_positions(),
        )
        if self.event_logger is not None:
            self.event_logger.log_summary(
                summary=runtime_result.summary,
                final_account_state=runtime_result.final_account_state,
                final_positions=runtime_result.final_positions,
            )
        if self.trade_repository is not None:
            self.trade_repository.save_runtime_result(
                runtime_result,
                event_log_path=(
                    self.event_logger.event_log_path
                    if self.event_logger is not None
                    else None
                ),
            )
        return runtime_result

    def _record_candidates(self, candidates: tuple) -> None:
        self.result_collector.record_candidates(candidates)
        if self.event_logger is None:
            return
        self.event_logger.log_filter_evaluations(
            self.strategy_coordinator.drain_filter_evaluation_log()
        )
        self.event_logger.log_candidates(candidates)

    def _record_signals(self, signals: tuple) -> None:
        self.result_collector.record_signals(signals)
        if self.event_logger is not None:
            self.event_logger.log_signals(signals)

    def _record_scores(self, scores: tuple) -> None:
        self.result_collector.record_scores(scores)
        if self.event_logger is not None:
            self.event_logger.log_scores(scores)

    def _record_order_requests(self, order_requests: tuple) -> None:
        self.result_collector.record_order_requests(order_requests)
        if self.event_logger is not None:
            self.event_logger.log_order_requests(order_requests)

    def _evaluate_operational_safety(self, trading_date: date, *, reason: str) -> None:
        if self.operational_safety_guard is None:
            return
        alerts = self.operational_safety_guard.evaluate_portfolio(
            trading_date=trading_date,
            reason=reason,
            account_state=self.portfolio_coordinator.current_account_state(),
            positions=self.portfolio_coordinator.current_positions(),
        )
        self._emit_alerts(alerts)

    def _emit_alerts(self, alerts: tuple[AlertNotification, ...]) -> None:
        if not alerts:
            return
        if self.event_logger is not None:
            self.event_logger.log_alerts(alerts)
        if self.alert_dispatcher is not None:
            self.alert_dispatcher.dispatch_all(alerts)

    def _filter_duplicate_signals(self, signals: tuple) -> tuple:
        if self.operational_safety_guard is None:
            return signals

        filtered_signals = []
        for signal in signals:
            side = "buy" if signal.signal_type == "buy" else "sell"
            is_allowed, alerts = self.operational_safety_guard.evaluate_duplicate_order(
                instrument_id=signal.instrument_id,
                side=side,
                timestamp=signal.timestamp,
                active_order_exists=self.portfolio_coordinator.has_active_order(
                    signal.instrument_id,
                    side,
                ),
            )
            self._emit_alerts(alerts)
            if is_allowed:
                filtered_signals.append(signal)
        return tuple(filtered_signals)

    def _apply_order_block_policy(
        self,
        *,
        close_entry_signals: tuple,
        close_exit_signals: tuple,
    ) -> tuple[tuple, tuple]:
        if self.operational_safety_guard is None:
            return close_entry_signals, close_exit_signals
        if self.operational_safety_guard.all_orders_halted:
            return (), ()
        if self.operational_safety_guard.entry_orders_blocked:
            return (), close_exit_signals
        return close_entry_signals, close_exit_signals

    def _filter_blocked_order_requests(
        self,
        trading_date: date,
        order_requests: tuple,
    ) -> tuple:
        if self.operational_safety_guard is None:
            return order_requests

        allowed_order_requests = []
        timestamp = self.portfolio_coordinator.current_account_state().timestamp
        for order_request in order_requests:
            if self.operational_safety_guard.should_allow_order(order_request):
                allowed_order_requests.append(order_request)
                continue
            self.portfolio_coordinator.release_order_request(
                order_request.order_request_id,
                timestamp=timestamp,
            )

        self._evaluate_operational_safety(
            trading_date,
            reason="next_open_pre_submission_filter",
        )
        return tuple(allowed_order_requests)

    def _filter_gap_blocked_order_requests(
        self,
        trading_date: date,
        order_requests: tuple,
        open_snapshots: dict,
    ) -> tuple:
        if self.gap_filter_policy is None:
            return order_requests

        previous_closes = self.strategy_coordinator.previous_closes_for_date(trading_date)
        decisions = []
        allowed_order_requests = []
        timestamp = self.portfolio_coordinator.current_account_state().timestamp
        for order_request in order_requests:
            open_snapshot = open_snapshots.get(order_request.instrument_id)
            if open_snapshot is None:
                allowed_order_requests.append(order_request)
                continue
            decision = self.gap_filter_policy.evaluate(
                order_request,
                open_snapshot=open_snapshot,
                previous_close=previous_closes.get(order_request.instrument_id),
            )
            decisions.append(decision)
            if decision.allowed:
                allowed_order_requests.append(order_request)
                continue
            self.portfolio_coordinator.release_order_request(
                order_request.order_request_id,
                timestamp=timestamp,
            )

        if decisions and self.event_logger is not None:
            self.event_logger.log_gap_filter_decisions(decisions)
        return tuple(allowed_order_requests)
