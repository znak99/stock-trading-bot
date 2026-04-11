"""Tests for core enums and interface contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from stock_trading_bot.core.enums import OrderEventType, OrderState
from stock_trading_bot.core.interfaces import Broker, ExitPolicy, Filter, RankingModel, Strategy
from stock_trading_bot.core.models import (
    CandidateSelectionResult,
    Instrument,
    MarketDataSnapshot,
    OrderEvent,
    OrderRequest,
    Position,
    ScoreResult,
    Signal,
)


def _build_snapshot() -> MarketDataSnapshot:
    return MarketDataSnapshot(
        snapshot_id="snap-001",
        instrument_id="instr-001",
        timestamp=datetime(2026, 4, 12, 15, 30, tzinfo=UTC),
        open_price=Decimal("70000"),
        high_price=Decimal("71000"),
        low_price=Decimal("69500"),
        close_price=Decimal("70800"),
        volume=1_250_000,
        trading_value=Decimal("88500000000"),
        change_rate=Decimal("0.012"),
        is_final=True,
        session_phase="MARKET_CLOSE_PROCESS",
    )


def _build_signal(signal_type: Literal["buy", "sell", "partial_sell"] = "buy") -> Signal:
    return Signal(
        signal_id="sig-001",
        instrument_id="instr-001",
        timestamp=datetime(2026, 4, 12, 15, 30, tzinfo=UTC),
        signal_type=signal_type,
        strategy_name="breakout_swing_v1",
        signal_strength=Decimal("0.80"),
        decision_reason="contract test",
        market_snapshot_ref="snap-001",
        candidate_ref="cand-001",
        target_execution_time=datetime(2026, 4, 13, 9, 0, tzinfo=UTC),
        is_confirmed=True,
    )


@dataclass
class FakeBroker:
    mode: str = "backtest"
    canceled_order_ids: list[str] = field(default_factory=list)

    def submit_order(self, order_request: OrderRequest) -> str:
        return f"broker-{order_request.order_request_id}"

    def cancel_order(self, order_request_id: str) -> None:
        self.canceled_order_ids.append(order_request_id)

    def poll_events(self) -> list[OrderEvent]:
        return []


@dataclass
class FakeStrategy:
    name: str = "fake_strategy"

    def evaluate_entry(
        self,
        candidate: CandidateSelectionResult,
        snapshot: MarketDataSnapshot,
    ) -> Signal | None:
        if candidate.passed and snapshot.is_final:
            return _build_signal("buy")
        return None

    def evaluate_exit(
        self,
        position: Position,
        snapshot: MarketDataSnapshot,
    ) -> list[Signal]:
        if position.position_status == "open" and snapshot.close_price < position.current_price:
            return [_build_signal("sell")]
        return []


@dataclass
class FakeFilter:
    name: str = "fake_filter"

    def evaluate(
        self,
        instrument: Instrument,
        snapshot: MarketDataSnapshot,
    ) -> tuple[bool, str]:
        passed = instrument.is_active and snapshot.volume > 0
        return passed, "passed" if passed else "inactive_or_zero_volume"


@dataclass
class FakeRankingModel:
    name: str = "fake_ranker"
    version: str = "v1"

    def score_candidate(
        self,
        candidate: CandidateSelectionResult,
        snapshot: MarketDataSnapshot,
    ) -> ScoreResult:
        return ScoreResult(
            score_id="score-001",
            instrument_id=candidate.instrument_id,
            timestamp=snapshot.timestamp,
            model_name=self.name,
            model_version=self.version,
            score_value=Decimal("0.75"),
            rank=1,
            feature_set_name="CoreFeatureSet",
            candidate_ref=candidate.candidate_id,
            score_reason_summary="contract test score",
        )


@dataclass
class FakeExitPolicy:
    name: str = "fake_exit_policy"

    def evaluate(
        self,
        position: Position,
        snapshot: MarketDataSnapshot,
    ) -> list[Signal]:
        if snapshot.close_price < position.avg_entry_price:
            return [_build_signal("sell")]
        return []


def test_order_enums_are_resolvable_by_value() -> None:
    assert OrderState.CREATED.value == "created"
    assert OrderState("accepted") is OrderState.ACCEPTED
    assert OrderState.PARTIALLY_FILLED == "partially_filled"

    assert OrderEventType.SUBMIT_ENQUEUED.value == "submit_enqueued"
    assert OrderEventType("full_fill") is OrderEventType.FULL_FILL
    assert OrderEventType.CANCEL_REQUESTED == "cancel_requested"


def test_protocol_based_mocks_can_be_created() -> None:
    snapshot = _build_snapshot()
    instrument = Instrument(
        instrument_id="instr-001",
        symbol="005930",
        name="Samsung Electronics",
        market="KOSPI",
        asset_type="stock",
        sector="electronics",
        is_etf=False,
        is_active=True,
    )
    candidate = CandidateSelectionResult(
        candidate_id="cand-001",
        instrument_id=instrument.instrument_id,
        timestamp=snapshot.timestamp,
        filter_policy_name="default_filter_policy",
        passed=True,
        passed_filters=("liquidity",),
        failed_filters=(),
        eligibility_reason="passed",
        market_snapshot_ref=snapshot.snapshot_id,
    )
    position = Position(
        position_id="pos-001",
        instrument_id=instrument.instrument_id,
        opened_at=snapshot.timestamp,
        updated_at=snapshot.timestamp,
        quantity=Decimal("10"),
        avg_entry_price=Decimal("70500"),
        current_price=Decimal("71000"),
        unrealized_pnl=Decimal("5000"),
        unrealized_pnl_rate=Decimal("0.007"),
        position_status="open",
        exit_policy_name="fake_exit_policy",
    )
    order_request = OrderRequest(
        order_request_id="req-001",
        instrument_id=instrument.instrument_id,
        timestamp=snapshot.timestamp,
        side="buy",
        order_type="market",
        quantity=Decimal("10"),
        price=snapshot.close_price,
        time_in_force="day",
        source_signal_id="sig-001",
        risk_check_ref="risk-001",
        broker_mode="backtest",
        request_reason="contract test",
    )

    broker = FakeBroker()
    strategy = FakeStrategy()
    market_filter = FakeFilter()
    ranking_model = FakeRankingModel()
    exit_policy = FakeExitPolicy()

    assert isinstance(broker, Broker)
    assert isinstance(strategy, Strategy)
    assert isinstance(market_filter, Filter)
    assert isinstance(ranking_model, RankingModel)
    assert isinstance(exit_policy, ExitPolicy)

    assert broker.submit_order(order_request) == "broker-req-001"
    assert strategy.evaluate_entry(candidate, snapshot) is not None
    assert market_filter.evaluate(instrument, snapshot) == (True, "passed")
    assert ranking_model.score_candidate(candidate, snapshot).candidate_ref == candidate.candidate_id
    assert exit_policy.evaluate(position, snapshot) == []
