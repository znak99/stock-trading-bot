"""Execution event processing through the state machine and portfolio updater."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from stock_trading_bot.core.enums import OrderState
from stock_trading_bot.core.models import OrderEvent
from stock_trading_bot.execution.services.order_manager import OrderManager
from stock_trading_bot.execution.state_machine import OrderStateMachine
from stock_trading_bot.portfolio import PortfolioUpdater


@dataclass(slots=True, frozen=True, kw_only=True)
class ProcessedOrderEvent:
    """Processed execution event with state transition metadata."""

    order_event: OrderEvent
    previous_state: OrderState
    new_state: OrderState


class FillProcessor:
    """Apply order events to tracked order state and optional portfolio state."""

    def __init__(
        self,
        *,
        order_manager: OrderManager,
        order_state_machine: OrderStateMachine | None = None,
        portfolio_updater: PortfolioUpdater | None = None,
    ) -> None:
        self._order_manager = order_manager
        self._order_state_machine = order_state_machine or OrderStateMachine()
        self._portfolio_updater = portfolio_updater

    def process_event(
        self,
        order_event: OrderEvent,
        *,
        market_price: Decimal | None = None,
    ) -> ProcessedOrderEvent:
        """Process a single order event through state transition and ledger update."""

        managed_order = self._order_manager.get_managed_order(order_event.order_request_id)
        previous_state = managed_order.state
        new_state = self._order_state_machine.transition(
            previous_state,
            order_event.event_type,
            remaining_quantity=order_event.remaining_quantity,
        )
        self._order_manager.apply_processed_event(order_event, new_state=new_state)
        if self._portfolio_updater is not None:
            self._portfolio_updater.apply_order_event(
                managed_order.order_request,
                order_event,
                market_price=market_price,
            )

        return ProcessedOrderEvent(
            order_event=order_event,
            previous_state=previous_state,
            new_state=new_state,
        )

    def process_events(
        self,
        order_events: tuple[OrderEvent, ...],
        *,
        market_price: Decimal | None = None,
    ) -> tuple[ProcessedOrderEvent, ...]:
        """Process multiple order events in sequence."""

        return tuple(
            self.process_event(order_event, market_price=market_price)
            for order_event in order_events
        )
