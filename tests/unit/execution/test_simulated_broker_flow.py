"""Tests for simulated broker and execution service flow."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from stock_trading_bot.adapters import SimulatedBroker, SimulatedFillStep
from stock_trading_bot.core.enums import OrderEventType, OrderState
from stock_trading_bot.core.models import AccountState, OrderRequest
from stock_trading_bot.execution import FillProcessor, OrderManager
from stock_trading_bot.portfolio import AccountStateStore, PortfolioUpdater, PositionBook


def _build_account_state() -> AccountState:
    return AccountState(
        account_state_id="account-001",
        timestamp=datetime(2026, 4, 12, 9, 0, tzinfo=UTC),
        broker_mode="backtest",
        total_equity=Decimal("1000000"),
        cash_balance=Decimal("1000000"),
        available_cash=Decimal("1000000"),
        market_value=Decimal("0"),
        active_position_count=0,
        max_position_limit=5,
        account_status="active",
    )


def _build_buy_order() -> OrderRequest:
    return OrderRequest(
        order_request_id="order-buy-001",
        instrument_id="instr-001",
        timestamp=datetime(2026, 4, 12, 9, 5, tzinfo=UTC),
        side="buy",
        order_type="market",
        quantity=Decimal("10"),
        price=Decimal("100"),
        time_in_force="day",
        source_signal_id="sig-001",
        risk_check_ref="risk-001",
        broker_mode="backtest",
        request_reason="entry",
    )


def test_simulated_broker_emits_submit_accept_partial_and_full_fill_events() -> None:
    order_request = _build_buy_order()
    broker = SimulatedBroker(
        fill_scenarios={
            order_request.order_request_id: (
                SimulatedFillStep(quantity=Decimal("4"), price=Decimal("100")),
                SimulatedFillStep(quantity=Decimal("6"), price=Decimal("103")),
            )
        }
    )

    broker.submit_order(order_request)

    initial_events = broker.poll_events()
    partial_fill_events = broker.poll_events()
    full_fill_events = broker.poll_events()

    assert [event.event_type for event in initial_events] == [
        OrderEventType.SUBMIT_SENT.value,
        OrderEventType.BROKER_ACCEPTED.value,
    ]
    assert len(partial_fill_events) == 1
    assert partial_fill_events[0].event_type == OrderEventType.PARTIAL_FILL.value
    assert partial_fill_events[0].filled_quantity == Decimal("4")
    assert partial_fill_events[0].remaining_quantity == Decimal("6")

    assert len(full_fill_events) == 1
    assert full_fill_events[0].event_type == OrderEventType.FULL_FILL.value
    assert full_fill_events[0].filled_quantity == Decimal("10")
    assert full_fill_events[0].filled_price_avg == Decimal("101.8")
    assert full_fill_events[0].remaining_quantity == Decimal("0")


def test_order_manager_and_fill_processor_drive_state_machine_and_portfolio_flow() -> None:
    order_request = _build_buy_order()
    broker = SimulatedBroker(
        fill_scenarios={
            order_request.order_request_id: (
                SimulatedFillStep(quantity=Decimal("4"), price=Decimal("100")),
                SimulatedFillStep(quantity=Decimal("6"), price=Decimal("103")),
            )
        }
    )
    order_manager = OrderManager(broker=broker)
    account_state_store = AccountStateStore(_build_account_state())
    position_book = PositionBook()
    portfolio_updater = PortfolioUpdater(
        position_book=position_book,
        account_state_store=account_state_store,
    )
    portfolio_updater.reserve_for_buy(order_request)
    fill_processor = FillProcessor(
        order_manager=order_manager,
        portfolio_updater=portfolio_updater,
    )

    submit_enqueued = order_manager.submit_order(order_request)
    submitted_result = fill_processor.process_event(submit_enqueued)
    first_broker_results = fill_processor.process_events(order_manager.poll_broker_events())
    second_broker_results = fill_processor.process_events(order_manager.poll_broker_events())
    final_broker_results = fill_processor.process_events(order_manager.poll_broker_events())

    managed_order = order_manager.get_managed_order(order_request.order_request_id)
    position = position_book.get(order_request.instrument_id)
    account_state = account_state_store.get_state()

    assert submitted_result.previous_state is OrderState.CREATED
    assert submitted_result.new_state is OrderState.PENDING_SUBMIT
    assert [result.new_state for result in first_broker_results] == [
        OrderState.SUBMITTED,
        OrderState.ACCEPTED,
    ]
    assert second_broker_results[0].new_state is OrderState.PARTIALLY_FILLED
    assert final_broker_results[0].new_state is OrderState.FILLED

    assert managed_order.state is OrderState.FILLED
    assert managed_order.filled_quantity == Decimal("10")
    assert managed_order.remaining_quantity == Decimal("0")
    assert position is not None
    assert position.quantity == Decimal("10")
    assert position.position_status == "open"
    assert account_state.reserved_cash == Decimal("0")
    assert account_state.available_cash == account_state.cash_balance
    assert account_state.active_position_count == 1
