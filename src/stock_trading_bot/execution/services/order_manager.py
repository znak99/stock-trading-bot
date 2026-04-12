"""Order lifecycle tracking and broker submission helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from stock_trading_bot.core.enums import OrderEventType, OrderState
from stock_trading_bot.core.interfaces import Broker
from stock_trading_bot.core.models import OrderEvent, OrderRequest


@dataclass(slots=True, kw_only=True)
class ManagedOrder:
    """Tracked execution order state and event history."""

    order_request: OrderRequest
    broker_order_id: str = ""
    state: OrderState = OrderState.CREATED
    filled_quantity: Decimal = Decimal("0")
    filled_price_avg: Decimal = Decimal("0")
    remaining_quantity: Decimal = Decimal("0")
    event_history: list[OrderEvent] = field(default_factory=list)


class OrderManager:
    """Submit orders to a broker and track their managed lifecycle state."""

    def __init__(self, *, broker: Broker) -> None:
        self._broker = broker
        self._managed_orders: dict[str, ManagedOrder] = {}

    def submit_order(self, order_request: OrderRequest) -> OrderEvent:
        """Register and submit an order, returning the local enqueue event."""

        if order_request.order_request_id in self._managed_orders:
            raise ValueError(f"Duplicate order_request_id={order_request.order_request_id!r}.")

        managed_order = ManagedOrder(
            order_request=order_request,
            remaining_quantity=order_request.quantity,
        )
        self._managed_orders[order_request.order_request_id] = managed_order
        managed_order.broker_order_id = self._broker.submit_order(order_request)
        return self._build_local_event(
            order_request=order_request,
            event_type=OrderEventType.SUBMIT_ENQUEUED,
            broker_order_id=managed_order.broker_order_id,
            filled_quantity=Decimal("0"),
            filled_price_avg=Decimal("0"),
            remaining_quantity=order_request.quantity,
            event_message="order enqueued for broker submission",
            is_terminal=False,
            timestamp=order_request.timestamp,
        )

    def request_cancel(self, order_request_id: str, *, timestamp: datetime | None = None) -> OrderEvent:
        """Request broker cancellation and return the local cancel-requested event."""

        managed_order = self.get_managed_order(order_request_id)
        self._broker.cancel_order(order_request_id)
        return self._build_local_event(
            order_request=managed_order.order_request,
            event_type=OrderEventType.CANCEL_REQUESTED,
            broker_order_id=managed_order.broker_order_id,
            filled_quantity=managed_order.filled_quantity,
            filled_price_avg=managed_order.filled_price_avg,
            remaining_quantity=managed_order.remaining_quantity,
            event_message="cancel requested",
            is_terminal=False,
            timestamp=timestamp or datetime.now(tz=UTC),
        )

    def poll_broker_events(self) -> tuple[OrderEvent, ...]:
        """Poll execution events from the broker."""

        return tuple(self._broker.poll_events())

    def get_managed_order(self, order_request_id: str) -> ManagedOrder:
        """Return the tracked order for the request id."""

        try:
            return self._managed_orders[order_request_id]
        except KeyError as error:
            raise ValueError(f"Unknown order_request_id={order_request_id!r}.") from error

    def apply_processed_event(self, order_event: OrderEvent, *, new_state: OrderState) -> ManagedOrder:
        """Persist processed event details into tracked order state."""

        managed_order = self.get_managed_order(order_event.order_request_id)
        managed_order.state = new_state
        managed_order.filled_quantity = order_event.filled_quantity
        managed_order.filled_price_avg = order_event.filled_price_avg
        managed_order.remaining_quantity = order_event.remaining_quantity
        if order_event.broker_order_id:
            managed_order.broker_order_id = order_event.broker_order_id
        managed_order.event_history.append(order_event)
        return managed_order

    @staticmethod
    def _build_local_event(
        *,
        order_request: OrderRequest,
        event_type: OrderEventType,
        broker_order_id: str,
        filled_quantity: Decimal,
        filled_price_avg: Decimal,
        remaining_quantity: Decimal,
        event_message: str,
        is_terminal: bool,
        timestamp: datetime,
    ) -> OrderEvent:
        return OrderEvent(
            order_event_id=f"event-{uuid4().hex}",
            order_request_id=order_request.order_request_id,
            timestamp=timestamp,
            event_type=event_type.value,
            broker_order_id=broker_order_id,
            filled_quantity=filled_quantity,
            filled_price_avg=filled_price_avg,
            remaining_quantity=remaining_quantity,
            event_message=event_message,
            is_terminal=is_terminal,
        )
