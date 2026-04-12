"""Backtest broker that emits deterministic simulated execution events."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from stock_trading_bot.core.enums import OrderEventType
from stock_trading_bot.core.models import OrderEvent, OrderRequest


@dataclass(slots=True, frozen=True, kw_only=True)
class SimulatedFillStep:
    """Single simulated fill increment."""

    quantity: Decimal
    price: Decimal


@dataclass(slots=True, kw_only=True)
class _SimulatedOrder:
    order_request: OrderRequest
    broker_order_id: str
    fill_steps: deque[SimulatedFillStep]
    filled_quantity: Decimal = Decimal("0")
    filled_notional: Decimal = Decimal("0")
    is_accepted: bool = False
    is_terminal: bool = False
    next_event_timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def remaining_quantity(self) -> Decimal:
        return self.order_request.quantity - self.filled_quantity


class SimulatedBroker:
    """Backtest broker that simulates submit, accept, partial fill, and full fill events."""

    mode = "backtest"

    def __init__(
        self,
        *,
        fill_scenarios: Mapping[str, Sequence[SimulatedFillStep]] | None = None,
        rejected_order_request_ids: Sequence[str] = (),
        event_interval: timedelta = timedelta(seconds=1),
    ) -> None:
        self._fill_scenarios = {
            order_request_id: tuple(fill_steps)
            for order_request_id, fill_steps in (fill_scenarios or {}).items()
        }
        self._rejected_order_request_ids = frozenset(rejected_order_request_ids)
        self._event_interval = event_interval
        self._orders_by_request_id: dict[str, _SimulatedOrder] = {}
        self._queued_events: deque[OrderEvent] = deque()

    def submit_order(self, order_request: OrderRequest) -> str:
        """Register a simulated order and queue submission events."""

        if order_request.order_request_id in self._orders_by_request_id:
            raise ValueError(f"Duplicate order_request_id={order_request.order_request_id!r}.")

        broker_order_id = f"broker-{uuid4().hex}"
        fill_steps = deque(self._resolve_fill_steps(order_request))
        simulated_order = _SimulatedOrder(
            order_request=order_request,
            broker_order_id=broker_order_id,
            fill_steps=fill_steps,
            next_event_timestamp=order_request.timestamp,
        )
        self._orders_by_request_id[order_request.order_request_id] = simulated_order

        self._queued_events.append(
            self._build_event(
                simulated_order=simulated_order,
                event_type=OrderEventType.SUBMIT_SENT,
                timestamp=simulated_order.next_event_timestamp,
                event_message="order submitted to simulated broker",
                is_terminal=False,
            )
        )
        simulated_order.next_event_timestamp += self._event_interval

        if order_request.order_request_id in self._rejected_order_request_ids:
            simulated_order.is_terminal = True
            self._queued_events.append(
                self._build_event(
                    simulated_order=simulated_order,
                    event_type=OrderEventType.BROKER_REJECTED,
                    timestamp=simulated_order.next_event_timestamp,
                    event_message="simulated broker rejected order",
                    is_terminal=True,
                )
            )
        else:
            self._queued_events.append(
                self._build_event(
                    simulated_order=simulated_order,
                    event_type=OrderEventType.BROKER_ACCEPTED,
                    timestamp=simulated_order.next_event_timestamp,
                    event_message="simulated broker accepted order",
                    is_terminal=False,
                )
            )

        simulated_order.next_event_timestamp += self._event_interval
        return broker_order_id

    def cancel_order(self, order_request_id: str) -> None:
        """Cancel the remaining simulated quantity for an order."""

        simulated_order = self._get_order(order_request_id)
        if simulated_order.is_terminal or simulated_order.remaining_quantity == Decimal("0"):
            raise ValueError(
                "Cannot cancel an order that is already terminal or fully filled. "
                f"order_request_id={order_request_id!r}"
            )

        simulated_order.fill_steps.clear()
        simulated_order.is_terminal = True
        self._queued_events.append(
            self._build_event(
                simulated_order=simulated_order,
                event_type=OrderEventType.CANCEL_CONFIRMED,
                timestamp=simulated_order.next_event_timestamp,
                event_message="simulated broker cancel confirmed",
                is_terminal=True,
            )
        )
        simulated_order.next_event_timestamp += self._event_interval

    def poll_events(self) -> tuple[OrderEvent, ...]:
        """Return queued events, generating the next fill wave when needed."""

        if self._queued_events:
            events = tuple(self._queued_events)
            self._queued_events.clear()
            return events

        generated_fill_events: list[OrderEvent] = []
        for simulated_order in self._orders_by_request_id.values():
            if (
                simulated_order.is_terminal
                or not simulated_order.is_accepted
                or not simulated_order.fill_steps
            ):
                continue

            next_fill_step = simulated_order.fill_steps.popleft()
            simulated_order.filled_quantity += next_fill_step.quantity
            simulated_order.filled_notional += next_fill_step.quantity * next_fill_step.price
            remaining_quantity = simulated_order.remaining_quantity
            is_terminal = remaining_quantity == Decimal("0")
            event_type = (
                OrderEventType.FULL_FILL if is_terminal else OrderEventType.PARTIAL_FILL
            )
            generated_fill_events.append(
                self._build_event(
                    simulated_order=simulated_order,
                    event_type=event_type,
                    timestamp=simulated_order.next_event_timestamp,
                    event_message="simulated fill generated",
                    is_terminal=is_terminal,
                )
            )
            simulated_order.next_event_timestamp += self._event_interval
            if is_terminal:
                simulated_order.is_terminal = True

        return tuple(generated_fill_events)

    def _resolve_fill_steps(self, order_request: OrderRequest) -> tuple[SimulatedFillStep, ...]:
        if order_request.order_request_id in self._fill_scenarios:
            fill_steps = self._fill_scenarios[order_request.order_request_id]
        else:
            fill_steps = (
                SimulatedFillStep(quantity=order_request.quantity, price=order_request.price),
            )

        total_quantity = sum((fill_step.quantity for fill_step in fill_steps), Decimal("0"))
        if total_quantity != order_request.quantity:
            raise ValueError(
                "Simulated fill steps must sum to the original order quantity. "
                f"order_request_id={order_request.order_request_id!r}"
            )
        return fill_steps

    def _get_order(self, order_request_id: str) -> _SimulatedOrder:
        try:
            return self._orders_by_request_id[order_request_id]
        except KeyError as error:
            raise ValueError(f"Unknown order_request_id={order_request_id!r}.") from error

    def _build_event(
        self,
        *,
        simulated_order: _SimulatedOrder,
        event_type: OrderEventType,
        timestamp: datetime,
        event_message: str,
        is_terminal: bool,
    ) -> OrderEvent:
        if event_type == OrderEventType.BROKER_ACCEPTED:
            simulated_order.is_accepted = True

        filled_price_avg = (
            simulated_order.filled_notional / simulated_order.filled_quantity
            if simulated_order.filled_quantity > Decimal("0")
            else Decimal("0")
        )
        return OrderEvent(
            order_event_id=f"event-{uuid4().hex}",
            order_request_id=simulated_order.order_request.order_request_id,
            timestamp=timestamp,
            event_type=event_type.value,
            broker_order_id=simulated_order.broker_order_id,
            filled_quantity=simulated_order.filled_quantity,
            filled_price_avg=filled_price_avg,
            remaining_quantity=simulated_order.remaining_quantity,
            event_message=event_message,
            is_terminal=is_terminal,
        )
