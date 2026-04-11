"""Tests for portfolio bookkeeping and risk logic."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from stock_trading_bot.core.enums import OrderEventType
from stock_trading_bot.core.models import AccountState, OrderEvent, OrderRequest, Position
from stock_trading_bot.portfolio import (
    AccountStateStore,
    EqualWeightAllocationPolicy,
    PortfolioUpdater,
    PositionBook,
    PreTradeRiskChecker,
)
from stock_trading_bot.portfolio.services import CostProfile


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


def _build_buy_order(quantity: str = "10", price: str = "100") -> OrderRequest:
    return OrderRequest(
        order_request_id="order-buy-001",
        instrument_id="instr-001",
        timestamp=datetime(2026, 4, 12, 9, 5, tzinfo=UTC),
        side="buy",
        order_type="market",
        quantity=Decimal(quantity),
        price=Decimal(price),
        time_in_force="day",
        source_signal_id="sig-001",
        risk_check_ref="risk-001",
        broker_mode="backtest",
        request_reason="entry",
    )


def _build_sell_order(quantity: str = "10", price: str = "110") -> OrderRequest:
    return OrderRequest(
        order_request_id="order-sell-001",
        instrument_id="instr-001",
        timestamp=datetime(2026, 4, 13, 9, 0, tzinfo=UTC),
        side="sell",
        order_type="market",
        quantity=Decimal(quantity),
        price=Decimal(price),
        time_in_force="day",
        source_signal_id="sig-002",
        risk_check_ref="risk-002",
        broker_mode="backtest",
        request_reason="exit",
    )


def _build_open_position() -> Position:
    return Position(
        position_id="pos-001",
        instrument_id="instr-001",
        opened_at=datetime(2026, 4, 12, 9, 10, tzinfo=UTC),
        updated_at=datetime(2026, 4, 12, 9, 11, tzinfo=UTC),
        quantity=Decimal("10"),
        avg_entry_price=Decimal("103.309000"),
        current_price=Decimal("105.315"),
        unrealized_pnl=Decimal("20.060000"),
        unrealized_pnl_rate=Decimal("0.019417480665"),
        position_status="open",
        exit_policy_name="conservative_exit_policy",
    )


def test_equal_weight_allocation_policy_returns_budget_and_quantity() -> None:
    policy = EqualWeightAllocationPolicy(max_position_ratio=Decimal("0.20"))
    account_state = _build_account_state()

    assert policy.target_capital(account_state) == Decimal("200000.00")
    assert policy.quantity_for_capital(Decimal("50000"), Decimal("200000")) == Decimal("4")


def test_pre_trade_risk_checker_blocks_over_allocated_buy_and_reserved_sell_conflict() -> None:
    position_book = PositionBook((_build_open_position(),))
    account_state = _build_account_state()
    account_state.reserved_sell_quantity["instr-001"] = Decimal("8")
    checker = PreTradeRiskChecker()

    buy_result = checker.check_order(_build_buy_order(quantity="5000"), account_state, PositionBook())
    sell_result = checker.check_order(_build_sell_order(quantity="5"), account_state, position_book)

    assert buy_result.passed is False
    assert "requested_quantity_exceeds_allowed_quantity" in buy_result.failure_reasons
    assert buy_result.allowed_quantity < Decimal("5000")

    assert sell_result.passed is False
    assert "requested_quantity_exceeds_tradable_sell_quantity" in sell_result.failure_reasons
    assert sell_result.allowed_quantity == Decimal("2")


def test_pre_trade_risk_checker_respects_configured_max_position_ratio() -> None:
    checker = PreTradeRiskChecker(max_position_ratio=Decimal("0.10"))

    result = checker.check_order(_build_buy_order(quantity="1000"), _build_account_state(), PositionBook())

    assert result.allowed_capital == Decimal("100000.00")
    assert result.allowed_quantity == Decimal("996")


def test_buy_partial_and_full_fill_updates_position_account_and_average_cost() -> None:
    cost_profile = CostProfile()
    account_store = AccountStateStore(_build_account_state())
    position_book = PositionBook()
    updater = PortfolioUpdater(
        position_book=position_book,
        account_state_store=account_store,
        cost_profile=cost_profile,
    )
    order_request = _build_buy_order()

    updater.reserve_for_buy(order_request)
    reserved_cash = cost_profile.estimate_buy_cash_requirement(Decimal("100"), Decimal("10"))

    assert account_store.get_state().reserved_cash == reserved_cash
    assert account_store.get_state().available_cash == Decimal("1000000") - reserved_cash

    partial_fill = OrderEvent(
        order_event_id="event-001",
        order_request_id=order_request.order_request_id,
        timestamp=datetime(2026, 4, 12, 9, 10, tzinfo=UTC),
        event_type=OrderEventType.PARTIAL_FILL.value,
        broker_order_id="broker-001",
        filled_quantity=Decimal("4"),
        filled_price_avg=Decimal("100"),
        remaining_quantity=Decimal("6"),
        event_message="partial fill",
        is_terminal=False,
    )
    full_fill = OrderEvent(
        order_event_id="event-002",
        order_request_id=order_request.order_request_id,
        timestamp=datetime(2026, 4, 12, 9, 11, tzinfo=UTC),
        event_type=OrderEventType.FULL_FILL.value,
        broker_order_id="broker-001",
        filled_quantity=Decimal("10"),
        filled_price_avg=Decimal("103"),
        remaining_quantity=Decimal("0"),
        event_message="full fill",
        is_terminal=True,
    )

    updater.apply_order_event(order_request, partial_fill)
    updater.apply_order_event(order_request, full_fill)

    first_effective_price = Decimal("100") * (Decimal("1") + cost_profile.buy_slippage_rate)
    first_gross = first_effective_price * Decimal("4")
    first_commission = first_gross * cost_profile.buy_commission_rate

    second_delta_raw_price = ((Decimal("10") * Decimal("103")) - (Decimal("4") * Decimal("100"))) / Decimal("6")
    second_effective_price = second_delta_raw_price * (Decimal("1") + cost_profile.buy_slippage_rate)
    second_gross = second_effective_price * Decimal("6")
    second_commission = second_gross * cost_profile.buy_commission_rate

    expected_cash_balance = Decimal("1000000") - (
        first_gross + first_commission + second_gross + second_commission
    )
    expected_avg_entry_price = (
        (Decimal("4") * first_effective_price) + (Decimal("6") * second_effective_price)
    ) / Decimal("10")
    expected_market_value = Decimal("10") * second_effective_price

    position = position_book.get("instr-001")
    account_state = account_store.get_state()

    assert position is not None
    assert position.quantity == Decimal("10")
    assert position.position_status == "open"
    assert position.avg_entry_price == expected_avg_entry_price
    assert position.current_price == second_effective_price
    assert account_state.cash_balance == expected_cash_balance
    assert account_state.available_cash == account_state.cash_balance
    assert account_state.reserved_cash == Decimal("0")
    assert account_state.accumulated_buy_commission == first_commission + second_commission
    assert account_state.market_value == expected_market_value
    assert account_state.total_equity == expected_cash_balance + expected_market_value
    assert account_state.active_position_count == 1


def test_buy_partial_fill_keeps_available_cash_stable_when_actual_fill_is_below_reserve_estimate() -> None:
    cost_profile = CostProfile()
    account_store = AccountStateStore(_build_account_state())
    position_book = PositionBook()
    updater = PortfolioUpdater(
        position_book=position_book,
        account_state_store=account_store,
        cost_profile=cost_profile,
    )
    order_request = _build_buy_order(quantity="10", price="100")

    updater.reserve_for_buy(order_request)
    available_cash_after_reservation = account_store.get_state().available_cash

    partial_fill = OrderEvent(
        order_event_id="event-050",
        order_request_id=order_request.order_request_id,
        timestamp=datetime(2026, 4, 12, 9, 8, tzinfo=UTC),
        event_type=OrderEventType.PARTIAL_FILL.value,
        broker_order_id="broker-050",
        filled_quantity=Decimal("5"),
        filled_price_avg=Decimal("95"),
        remaining_quantity=Decimal("5"),
        event_message="discounted partial fill",
        is_terminal=False,
    )

    updater.apply_order_event(order_request, partial_fill)

    account_state = account_store.get_state()

    assert account_state.available_cash == available_cash_after_reservation
    assert account_state.cash_balance - account_state.reserved_cash == account_state.available_cash


def test_sell_partial_and_full_fill_updates_realized_pnl_and_closes_position() -> None:
    cost_profile = CostProfile()
    account_state = _build_account_state()
    account_state.cash_balance = Decimal("998966.652250")
    account_state.available_cash = Decimal("998966.652250")
    account_state.market_value = Decimal("1053.150")
    account_state.total_equity = Decimal("1000019.802250")
    account_state.active_position_count = 1

    account_store = AccountStateStore(account_state)
    position_book = PositionBook((_build_open_position(),))
    updater = PortfolioUpdater(
        position_book=position_book,
        account_state_store=account_store,
        cost_profile=cost_profile,
    )
    order_request = _build_sell_order()

    updater.reserve_for_sell(order_request)
    assert account_store.get_state().reserved_sell_quantity["instr-001"] == Decimal("10")

    partial_fill = OrderEvent(
        order_event_id="event-101",
        order_request_id=order_request.order_request_id,
        timestamp=datetime(2026, 4, 13, 9, 1, tzinfo=UTC),
        event_type=OrderEventType.PARTIAL_FILL.value,
        broker_order_id="broker-002",
        filled_quantity=Decimal("4"),
        filled_price_avg=Decimal("110"),
        remaining_quantity=Decimal("6"),
        event_message="partial sell fill",
        is_terminal=False,
    )
    full_fill = OrderEvent(
        order_event_id="event-102",
        order_request_id=order_request.order_request_id,
        timestamp=datetime(2026, 4, 13, 9, 2, tzinfo=UTC),
        event_type=OrderEventType.FULL_FILL.value,
        broker_order_id="broker-002",
        filled_quantity=Decimal("10"),
        filled_price_avg=Decimal("110"),
        remaining_quantity=Decimal("0"),
        event_message="full sell fill",
        is_terminal=True,
    )

    updater.apply_order_event(order_request, partial_fill)
    updater.apply_order_event(order_request, full_fill)

    effective_sell_price = Decimal("110") * (Decimal("1") - cost_profile.sell_slippage_rate)
    partial_gross = effective_sell_price * Decimal("4")
    partial_commission = partial_gross * cost_profile.sell_commission_rate
    partial_tax = partial_gross * cost_profile.sell_tax_rate
    partial_net = partial_gross - partial_commission - partial_tax
    partial_realized = (
        (effective_sell_price - Decimal("103.309000")) * Decimal("4")
    ) - partial_commission - partial_tax

    full_gross = effective_sell_price * Decimal("6")
    full_commission = full_gross * cost_profile.sell_commission_rate
    full_tax = full_gross * cost_profile.sell_tax_rate
    full_net = full_gross - full_commission - full_tax
    full_realized = (
        (effective_sell_price - Decimal("103.309000")) * Decimal("6")
    ) - full_commission - full_tax

    updated_position = position_book.get("instr-001")
    updated_account = account_store.get_state()

    assert updated_position is not None
    assert updated_position.quantity == Decimal("0")
    assert updated_position.position_status == "closed"
    assert updated_account.cash_balance == Decimal("998966.652250") + partial_net + full_net
    assert updated_account.realized_pnl == partial_realized + full_realized
    assert updated_account.accumulated_sell_commission == partial_commission + full_commission
    assert updated_account.accumulated_sell_tax == partial_tax + full_tax
    assert updated_account.reserved_sell_quantity == {}
    assert updated_account.market_value == Decimal("0")
    assert updated_account.total_equity == updated_account.cash_balance
    assert updated_account.active_position_count == 0


def test_cancelled_buy_releases_remaining_reserved_cash_and_keeps_filled_position() -> None:
    account_store = AccountStateStore(_build_account_state())
    position_book = PositionBook()
    updater = PortfolioUpdater(position_book=position_book, account_state_store=account_store)
    order_request = _build_buy_order()

    updater.reserve_for_buy(order_request)
    updater.apply_order_event(
        order_request,
        OrderEvent(
            order_event_id="event-201",
            order_request_id=order_request.order_request_id,
            timestamp=datetime(2026, 4, 12, 9, 10, tzinfo=UTC),
            event_type=OrderEventType.PARTIAL_FILL.value,
            broker_order_id="broker-003",
            filled_quantity=Decimal("4"),
            filled_price_avg=Decimal("100"),
            remaining_quantity=Decimal("6"),
            event_message="partial fill before cancel",
            is_terminal=False,
        ),
    )
    updater.apply_order_event(
        order_request,
        OrderEvent(
            order_event_id="event-202",
            order_request_id=order_request.order_request_id,
            timestamp=datetime(2026, 4, 12, 9, 12, tzinfo=UTC),
            event_type=OrderEventType.CANCEL_CONFIRMED.value,
            broker_order_id="broker-003",
            filled_quantity=Decimal("4"),
            filled_price_avg=Decimal("100"),
            remaining_quantity=Decimal("6"),
            event_message="cancel confirmed",
            is_terminal=True,
        ),
    )

    position = position_book.get("instr-001")
    account_state = account_store.get_state()

    assert position is not None
    assert position.quantity == Decimal("4")
    assert position.position_status == "open"
    assert account_state.reserved_cash == Decimal("0")
    assert account_state.available_cash == account_state.cash_balance


def test_broker_rejected_buy_releases_reserved_cash_without_creating_position() -> None:
    account_store = AccountStateStore(_build_account_state())
    position_book = PositionBook()
    updater = PortfolioUpdater(position_book=position_book, account_state_store=account_store)
    order_request = _build_buy_order()

    updater.reserve_for_buy(order_request)
    updater.apply_order_event(
        order_request,
        OrderEvent(
            order_event_id="event-301",
            order_request_id=order_request.order_request_id,
            timestamp=datetime(2026, 4, 12, 9, 7, tzinfo=UTC),
            event_type=OrderEventType.BROKER_REJECTED.value,
            broker_order_id="broker-301",
            filled_quantity=Decimal("0"),
            filled_price_avg=Decimal("0"),
            remaining_quantity=Decimal("10"),
            event_message="broker rejected",
            is_terminal=True,
        ),
    )

    account_state = account_store.get_state()

    assert position_book.get("instr-001") is None
    assert account_state.cash_balance == Decimal("1000000")
    assert account_state.reserved_cash == Decimal("0")
    assert account_state.available_cash == Decimal("1000000")


def test_expired_sell_releases_reserved_quantity_and_keeps_position() -> None:
    account_store = AccountStateStore(_build_account_state())
    position_book = PositionBook((_build_open_position(),))
    updater = PortfolioUpdater(position_book=position_book, account_state_store=account_store)
    order_request = _build_sell_order(quantity="6")

    updater.reserve_for_sell(order_request)
    updater.apply_order_event(
        order_request,
        OrderEvent(
            order_event_id="event-302",
            order_request_id=order_request.order_request_id,
            timestamp=datetime(2026, 4, 13, 9, 5, tzinfo=UTC),
            event_type=OrderEventType.EXPIRED.value,
            broker_order_id="broker-302",
            filled_quantity=Decimal("0"),
            filled_price_avg=Decimal("0"),
            remaining_quantity=Decimal("6"),
            event_message="sell order expired",
            is_terminal=True,
        ),
    )

    position = position_book.get("instr-001")
    account_state = account_store.get_state()

    assert position is not None
    assert position.quantity == Decimal("10")
    assert position.position_status == "open"
    assert account_state.reserved_sell_quantity == {}
    assert account_state.cash_balance == Decimal("1000000")


def test_late_fill_after_cancel_request_updates_book_and_releases_remaining_buy_reservation() -> None:
    account_store = AccountStateStore(_build_account_state())
    position_book = PositionBook()
    updater = PortfolioUpdater(position_book=position_book, account_state_store=account_store)
    order_request = _build_buy_order()

    updater.reserve_for_buy(order_request)
    updater.apply_order_event(
        order_request,
        OrderEvent(
            order_event_id="event-303",
            order_request_id=order_request.order_request_id,
            timestamp=datetime(2026, 4, 12, 9, 9, tzinfo=UTC),
            event_type=OrderEventType.LATE_FILL_AFTER_CANCEL_REQUEST.value,
            broker_order_id="broker-303",
            filled_quantity=Decimal("4"),
            filled_price_avg=Decimal("100"),
            remaining_quantity=Decimal("6"),
            event_message="late fill after cancel request",
            is_terminal=False,
        ),
    )
    updater.apply_order_event(
        order_request,
        OrderEvent(
            order_event_id="event-304",
            order_request_id=order_request.order_request_id,
            timestamp=datetime(2026, 4, 12, 9, 10, tzinfo=UTC),
            event_type=OrderEventType.CANCEL_CONFIRMED.value,
            broker_order_id="broker-303",
            filled_quantity=Decimal("4"),
            filled_price_avg=Decimal("100"),
            remaining_quantity=Decimal("6"),
            event_message="cancel confirmed after late fill",
            is_terminal=True,
        ),
    )

    position = position_book.get("instr-001")
    account_state = account_store.get_state()

    assert position is not None
    assert position.quantity == Decimal("4")
    assert position.position_status == "open"
    assert account_state.reserved_cash == Decimal("0")
    assert account_state.available_cash == account_state.cash_balance
