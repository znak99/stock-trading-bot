"""Tests for the order state machine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from stock_trading_bot.core.enums import OrderEventType, OrderState
from stock_trading_bot.execution.state_machine import (
    InvalidOrderTransitionError,
    MissingTransitionContextError,
    OrderStateMachine,
)


@pytest.mark.parametrize(
    ("current_state", "event_type", "expected_state", "remaining_quantity"),
    [
        (OrderState.CREATED, OrderEventType.SUBMIT_ENQUEUED, OrderState.PENDING_SUBMIT, None),
        (OrderState.PENDING_SUBMIT, OrderEventType.SUBMIT_SENT, OrderState.SUBMITTED, None),
        (OrderState.PENDING_SUBMIT, OrderEventType.SUBMIT_TIMEOUT, OrderState.PENDING_SUBMIT, None),
        (OrderState.PENDING_SUBMIT, OrderEventType.CANCELED_BEFORE_SUBMIT, OrderState.CANCELED, None),
        (OrderState.PENDING_SUBMIT, OrderEventType.INTERNAL_REJECTED, OrderState.REJECTED, None),
        (OrderState.SUBMITTED, OrderEventType.BROKER_ACCEPTED, OrderState.ACCEPTED, None),
        (OrderState.SUBMITTED, OrderEventType.BROKER_REJECTED, OrderState.REJECTED, None),
        (OrderState.SUBMITTED, OrderEventType.SUBMIT_TIMEOUT, OrderState.SUBMITTED, None),
        (OrderState.ACCEPTED, OrderEventType.PARTIAL_FILL, OrderState.PARTIALLY_FILLED, None),
        (OrderState.ACCEPTED, OrderEventType.FULL_FILL, OrderState.FILLED, None),
        (OrderState.ACCEPTED, OrderEventType.CANCEL_REQUESTED, OrderState.CANCEL_PENDING, None),
        (OrderState.ACCEPTED, OrderEventType.EXPIRED, OrderState.EXPIRED, None),
        (
            OrderState.PARTIALLY_FILLED,
            OrderEventType.PARTIAL_FILL,
            OrderState.PARTIALLY_FILLED,
            None,
        ),
        (OrderState.PARTIALLY_FILLED, OrderEventType.FULL_FILL, OrderState.FILLED, None),
        (
            OrderState.PARTIALLY_FILLED,
            OrderEventType.CANCEL_REQUESTED,
            OrderState.CANCEL_PENDING,
            None,
        ),
        (OrderState.PARTIALLY_FILLED, OrderEventType.EXPIRED, OrderState.EXPIRED, None),
        (OrderState.CANCEL_PENDING, OrderEventType.CANCEL_CONFIRMED, OrderState.CANCELED, None),
        (
            OrderState.CANCEL_PENDING,
            OrderEventType.CANCEL_REJECTED,
            OrderState.CANCEL_PENDING,
            None,
        ),
        (
            OrderState.CANCEL_PENDING,
            OrderEventType.LATE_FILL_AFTER_CANCEL_REQUEST,
            OrderState.PARTIALLY_FILLED,
            Decimal("3"),
        ),
        (
            OrderState.CANCEL_PENDING,
            OrderEventType.LATE_FILL_AFTER_CANCEL_REQUEST,
            OrderState.FILLED,
            Decimal("0"),
        ),
    ],
)
def test_order_state_machine_allows_documented_transitions(
    current_state: OrderState,
    event_type: OrderEventType,
    expected_state: OrderState,
    remaining_quantity: Decimal | None,
) -> None:
    state_machine = OrderStateMachine()

    next_state = state_machine.transition(
        current_state,
        event_type,
        remaining_quantity=remaining_quantity,
    )

    assert next_state is expected_state


@pytest.mark.parametrize(
    ("current_state", "event_type"),
    [
        (OrderState.CREATED, OrderEventType.FULL_FILL),
        (OrderState.ACCEPTED, OrderEventType.SUBMIT_SENT),
        (OrderState.PENDING_SUBMIT, OrderEventType.CANCEL_CONFIRMED),
        (OrderState.SUBMITTED, OrderEventType.CANCEL_REQUESTED),
    ],
)
def test_order_state_machine_rejects_forbidden_transitions(
    current_state: OrderState,
    event_type: OrderEventType,
) -> None:
    state_machine = OrderStateMachine()

    with pytest.raises(InvalidOrderTransitionError):
        state_machine.transition(current_state, event_type)


@pytest.mark.parametrize(
    "terminal_state",
    [
        OrderState.FILLED,
        OrderState.CANCELED,
        OrderState.REJECTED,
        OrderState.EXPIRED,
    ],
)
def test_terminal_states_cannot_transition(terminal_state: OrderState) -> None:
    state_machine = OrderStateMachine()

    assert state_machine.is_terminal(terminal_state) is True

    with pytest.raises(InvalidOrderTransitionError):
        state_machine.transition(terminal_state, OrderEventType.CANCEL_REQUESTED)


def test_non_terminal_states_are_reported_correctly() -> None:
    state_machine = OrderStateMachine()

    assert state_machine.is_terminal(OrderState.ACCEPTED) is False
    assert state_machine.is_terminal("pending_submit") is False


def test_late_fill_requires_remaining_quantity_context() -> None:
    state_machine = OrderStateMachine()

    with pytest.raises(MissingTransitionContextError):
        state_machine.transition(
            OrderState.CANCEL_PENDING,
            OrderEventType.LATE_FILL_AFTER_CANCEL_REQUEST,
        )
