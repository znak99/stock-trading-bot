"""Order state transition logic."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import TypeAlias

from stock_trading_bot.core.enums import OrderEventType, OrderState

StateLike: TypeAlias = OrderState | str
EventLike: TypeAlias = OrderEventType | str


class InvalidOrderTransitionError(ValueError):
    """Raised when an order attempts a transition not allowed by the spec."""

    def __init__(self, current_state: OrderState, event_type: OrderEventType, detail: str) -> None:
        self.current_state = current_state
        self.event_type = event_type
        message = (
            f"Invalid order transition: state={current_state.value!r}, "
            f"event={event_type.value!r}. {detail}"
        )
        super().__init__(message)


class MissingTransitionContextError(InvalidOrderTransitionError):
    """Raised when an allowed transition requires additional context to resolve."""


TransitionResolver: TypeAlias = Callable[[OrderState, OrderEventType, Decimal | None], OrderState]
TransitionTarget: TypeAlias = OrderState | TransitionResolver


class OrderStateMachine:
    """Table-driven state machine for order lifecycle transitions."""

    TERMINAL_STATES = frozenset(
        {
            OrderState.FILLED,
            OrderState.CANCELED,
            OrderState.REJECTED,
            OrderState.EXPIRED,
        }
    )

    def __init__(self) -> None:
        self._transitions: dict[OrderState, dict[OrderEventType, TransitionTarget]] = {
            OrderState.CREATED: {
                OrderEventType.SUBMIT_ENQUEUED: OrderState.PENDING_SUBMIT,
            },
            OrderState.PENDING_SUBMIT: {
                OrderEventType.SUBMIT_SENT: OrderState.SUBMITTED,
                OrderEventType.SUBMIT_TIMEOUT: OrderState.PENDING_SUBMIT,
                OrderEventType.CANCELED_BEFORE_SUBMIT: OrderState.CANCELED,
                OrderEventType.INTERNAL_REJECTED: OrderState.REJECTED,
            },
            OrderState.SUBMITTED: {
                OrderEventType.SUBMIT_TIMEOUT: OrderState.SUBMITTED,
                OrderEventType.BROKER_ACCEPTED: OrderState.ACCEPTED,
                OrderEventType.BROKER_REJECTED: OrderState.REJECTED,
                OrderEventType.INTERNAL_REJECTED: OrderState.REJECTED,
            },
            OrderState.ACCEPTED: {
                OrderEventType.PARTIAL_FILL: OrderState.PARTIALLY_FILLED,
                OrderEventType.FULL_FILL: OrderState.FILLED,
                OrderEventType.CANCEL_REQUESTED: OrderState.CANCEL_PENDING,
                OrderEventType.EXPIRED: OrderState.EXPIRED,
            },
            OrderState.PARTIALLY_FILLED: {
                OrderEventType.PARTIAL_FILL: OrderState.PARTIALLY_FILLED,
                OrderEventType.FULL_FILL: OrderState.FILLED,
                OrderEventType.CANCEL_REQUESTED: OrderState.CANCEL_PENDING,
                OrderEventType.EXPIRED: OrderState.EXPIRED,
            },
            OrderState.CANCEL_PENDING: {
                OrderEventType.CANCEL_CONFIRMED: OrderState.CANCELED,
                OrderEventType.CANCEL_REJECTED: OrderState.CANCEL_PENDING,
                OrderEventType.LATE_FILL_AFTER_CANCEL_REQUEST: self._resolve_late_fill,
            },
            OrderState.CANCELED: {},
            OrderState.FILLED: {},
            OrderState.REJECTED: {},
            OrderState.EXPIRED: {},
        }

    def transition(
        self,
        current_state: StateLike,
        event_type: EventLike,
        *,
        remaining_quantity: Decimal | None = None,
    ) -> OrderState:
        """Return the next state for a valid transition."""

        normalized_state = self._normalize_state(current_state)
        normalized_event = self._normalize_event(event_type)
        self.validate_transition(
            normalized_state,
            normalized_event,
            remaining_quantity=remaining_quantity,
        )

        transition_target = self._transitions[normalized_state][normalized_event]
        if isinstance(transition_target, OrderState):
            return transition_target

        return transition_target(
            normalized_state,
            normalized_event,
            remaining_quantity,
        )

    def validate_transition(
        self,
        current_state: StateLike,
        event_type: EventLike,
        *,
        remaining_quantity: Decimal | None = None,
    ) -> None:
        """Validate a transition and raise when it is not allowed."""

        normalized_state = self._normalize_state(current_state)
        normalized_event = self._normalize_event(event_type)

        if self.is_terminal(normalized_state):
            raise InvalidOrderTransitionError(
                normalized_state,
                normalized_event,
                "Terminal states cannot transition back into the active lifecycle.",
            )

        allowed_transitions = self._transitions.get(normalized_state, {})
        if normalized_event not in allowed_transitions:
            allowed_event_names = ", ".join(
                event.value for event in sorted(allowed_transitions, key=lambda item: item.value)
            )
            raise InvalidOrderTransitionError(
                normalized_state,
                normalized_event,
                f"Allowed events: [{allowed_event_names}]",
            )

        transition_target = allowed_transitions[normalized_event]
        if callable(transition_target):
            transition_target(normalized_state, normalized_event, remaining_quantity)

    def is_terminal(self, state: StateLike) -> bool:
        """Return whether the provided state is terminal."""

        normalized_state = self._normalize_state(state)
        return normalized_state in self.TERMINAL_STATES

    @staticmethod
    def _normalize_state(state: StateLike) -> OrderState:
        return state if isinstance(state, OrderState) else OrderState(state)

    @staticmethod
    def _normalize_event(event_type: EventLike) -> OrderEventType:
        return event_type if isinstance(event_type, OrderEventType) else OrderEventType(event_type)

    @staticmethod
    def _resolve_late_fill(
        current_state: OrderState,
        event_type: OrderEventType,
        remaining_quantity: Decimal | None,
    ) -> OrderState:
        if remaining_quantity is None:
            raise MissingTransitionContextError(
                current_state,
                event_type,
                "remaining_quantity is required to resolve late-fill transitions.",
            )
        if remaining_quantity < Decimal("0"):
            raise MissingTransitionContextError(
                current_state,
                event_type,
                "remaining_quantity cannot be negative.",
            )
        if remaining_quantity == Decimal("0"):
            return OrderState.FILLED
        return OrderState.PARTIALLY_FILLED

