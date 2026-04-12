"""Operational safety guard and runtime integration tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from stock_trading_bot.core.models import (
    AccountState,
    CandidateSelectionResult,
    MarketDataSnapshot,
    Position,
    ScoreResult,
    Signal,
)
from stock_trading_bot.infrastructure.notifications import AlertDispatcher, RecordingAlertNotifier
from stock_trading_bot.runtime import (
    ExecutionRuntime,
    OperationalSafetyConfig,
    OperationalSafetyGuard,
    PortfolioCoordinator,
    ResultCollector,
)


def _build_account_state(*, total_equity: str = "1000000") -> AccountState:
    return AccountState(
        account_state_id="account-safety-001",
        timestamp=datetime(2026, 4, 13, 9, 0, tzinfo=UTC),
        broker_mode="backtest",
        total_equity=Decimal(total_equity),
        cash_balance=Decimal("800000"),
        available_cash=Decimal("800000"),
        market_value=Decimal("200000"),
        active_position_count=1,
        max_position_limit=5,
        account_status="active",
    )


def _build_position(*, quantity: str = "2000") -> Position:
    return Position(
        position_id="position:LOSS",
        instrument_id="LOSS",
        opened_at=datetime(2026, 4, 12, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 4, 13, 9, 0, tzinfo=UTC),
        quantity=Decimal(quantity),
        avg_entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        unrealized_pnl_rate=Decimal("0"),
        position_status="open",
        exit_policy_name="conservative_exit_policy",
    )


def test_operational_safety_guard_blocks_new_buys_after_daily_loss_limit_breach() -> None:
    guard = OperationalSafetyGuard(
        config=OperationalSafetyConfig(daily_loss_limit_rate=Decimal("0.03"))
    )
    account_state = _build_account_state()
    guard.start_trading_day(date(2026, 4, 13), account_state)

    account_state.total_equity = Decimal("960000")
    alerts = guard.evaluate_portfolio(
        trading_date=date(2026, 4, 13),
        reason="intraday_mark_to_market",
        account_state=account_state,
        positions=(_build_position(),),
    )

    assert guard.entry_orders_blocked is True
    assert guard.all_orders_halted is False
    assert len(alerts) == 1
    assert alerts[0].code == "daily_loss_limit_breached"


def test_operational_safety_guard_halts_all_orders_on_abnormal_state() -> None:
    guard = OperationalSafetyGuard()
    account_state = _build_account_state()
    account_state.available_cash = Decimal("900000")

    alerts = guard.evaluate_portfolio(
        trading_date=date(2026, 4, 13),
        reason="pre_market",
        account_state=account_state,
        positions=(_build_position(),),
    )

    assert guard.all_orders_halted is True
    assert len(alerts) == 1
    assert alerts[0].code == "abnormal_state_detected"
    assert "available_cash_inconsistency" in alerts[0].metadata["abnormalities"]


def test_execution_runtime_blocks_entry_orders_after_daily_loss_limit_breach() -> None:
    recording_notifier = RecordingAlertNotifier()
    dispatcher = AlertDispatcher(notifiers=(recording_notifier,))
    strategy_coordinator = _StubStrategyCoordinator()
    portfolio_coordinator = _build_portfolio_coordinator_with_open_loss_position()
    runtime = ExecutionRuntime(
        session_clock=_StubSessionClock(),
        strategy_coordinator=strategy_coordinator,
        execution_coordinator=object(),
        portfolio_coordinator=portfolio_coordinator,
        result_collector=ResultCollector(),
        operational_safety_guard=OperationalSafetyGuard(
            config=OperationalSafetyConfig(daily_loss_limit_rate=Decimal("0.03"))
        ),
        alert_dispatcher=dispatcher,
    )

    runtime.run_pre_market(date(2026, 4, 13))
    runtime.run_market_close_process(date(2026, 4, 13))

    assert runtime.result_collector.order_requests == []
    assert len(recording_notifier.notifications) == 1
    assert recording_notifier.notifications[0].code == "daily_loss_limit_breached"


class _StubSessionClock:
    def next_trading_date(self, current_date: date) -> date:
        return current_date


class _StubStrategyCoordinator:
    def __init__(self) -> None:
        self._candidate = CandidateSelectionResult(
            candidate_id="candidate:BUY:20260413",
            instrument_id="BUY",
            timestamp=datetime(2026, 4, 13, 15, 20, tzinfo=UTC),
            filter_policy_name="default_filter_policy",
            passed=True,
            eligibility_reason="passed_all_filters",
            market_snapshot_ref="snapshot:BUY:20260413",
            passed_filters=("liquidity",),
            failed_filters=(),
        )
        self._signal = Signal(
            signal_id="signal:BUY:20260413",
            instrument_id="BUY",
            timestamp=datetime(2026, 4, 13, 15, 20, tzinfo=UTC),
            signal_type="buy",
            strategy_name="breakout_swing_v1",
            signal_strength=Decimal("0.9"),
            decision_reason="breakout_confirmed",
            market_snapshot_ref="snapshot:BUY:20260413",
            candidate_ref=self._candidate.candidate_id,
            target_execution_time=datetime(2026, 4, 13, 9, 0, tzinfo=UTC),
            is_confirmed=True,
        )
        self._score = ScoreResult(
            score_id="score:BUY:20260413",
            instrument_id="BUY",
            timestamp=datetime(2026, 4, 13, 15, 20, tzinfo=UTC),
            model_name="basic_ranking_model",
            model_version="v1",
            score_value=Decimal("0.82"),
            rank=1,
            feature_set_name="core_feature_set_v1",
            candidate_ref=self._candidate.candidate_id,
            score_reason_summary="test score",
        )

    def snapshots_for_date(
        self,
        trading_date: date,
        *,
        session_phase: str,
        is_final: bool,
    ) -> dict[str, MarketDataSnapshot]:
        del trading_date, session_phase, is_final
        return {
            "LOSS": MarketDataSnapshot(
                snapshot_id="snapshot:LOSS:20260413",
                instrument_id="LOSS",
                timestamp=datetime(2026, 4, 13, 15, 20, tzinfo=UTC),
                open_price=Decimal("82"),
                high_price=Decimal("84"),
                low_price=Decimal("79"),
                close_price=Decimal("80"),
                volume=100000,
                trading_value=Decimal("8000000"),
                change_rate=Decimal("-0.20"),
                is_final=True,
                session_phase="MARKET_CLOSE_PROCESS",
            ),
            "BUY": MarketDataSnapshot(
                snapshot_id="snapshot:BUY:20260413",
                instrument_id="BUY",
                timestamp=datetime(2026, 4, 13, 15, 20, tzinfo=UTC),
                open_price=Decimal("50"),
                high_price=Decimal("55"),
                low_price=Decimal("49"),
                close_price=Decimal("54"),
                volume=200000,
                trading_value=Decimal("10800000"),
                change_rate=Decimal("0.05"),
                is_final=True,
                session_phase="MARKET_CLOSE_PROCESS",
            ),
        }

    def select_close_candidates(self, trading_date: date) -> tuple[CandidateSelectionResult, ...]:
        del trading_date
        return (self._candidate,)

    def confirm_close_candidates(
        self,
        trading_date: date,
        *,
        candidates: tuple[CandidateSelectionResult, ...],
        snapshots_by_instrument_id: dict[str, MarketDataSnapshot],
    ) -> tuple[Signal, ...]:
        del trading_date, candidates, snapshots_by_instrument_id
        return (self._signal,)

    def evaluate_exit_signals(
        self,
        trading_date: date,
        positions: tuple[Position, ...],
        *,
        session_phase: str,
        is_final: bool,
    ) -> tuple[Signal, ...]:
        del trading_date, positions, session_phase, is_final
        return ()

    def rank_candidates(
        self,
        candidates: tuple[CandidateSelectionResult, ...],
        *,
        signals: tuple[Signal, ...],
        snapshots_by_instrument_id: dict[str, MarketDataSnapshot],
    ) -> tuple[ScoreResult, ...]:
        del candidates, signals, snapshots_by_instrument_id
        return (self._score,)

    def drain_filter_evaluation_log(self) -> tuple[object, ...]:
        return ()


def _build_portfolio_coordinator_with_open_loss_position() -> PortfolioCoordinator:
    from stock_trading_bot.portfolio import (
        AccountStateStore,
        EqualWeightAllocationPolicy,
        PortfolioUpdater,
        PositionBook,
        PreTradeRiskChecker,
    )

    position = _build_position()
    position_book = PositionBook((position,))
    account_state_store = AccountStateStore(_build_account_state())
    account_state_store.recalculate_summary(position_book)
    allocation_policy = EqualWeightAllocationPolicy(max_position_ratio=Decimal("0.20"))
    risk_checker = PreTradeRiskChecker(allocation_policy=allocation_policy)
    portfolio_updater = PortfolioUpdater(
        position_book=position_book,
        account_state_store=account_state_store,
    )
    return PortfolioCoordinator(
        position_book=position_book,
        account_state_store=account_state_store,
        risk_checker=risk_checker,
        portfolio_updater=portfolio_updater,
        allocation_policy=allocation_policy,
        broker_mode="backtest",
        block_duplicate_active_orders=True,
    )
