"""Execution coordination between the broker, state machine, and portfolio."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from stock_trading_bot.core.models import MarketDataSnapshot, OrderEvent, OrderRequest
from stock_trading_bot.execution import FillProcessor, OrderManager, ProcessedOrderEvent
from stock_trading_bot.infrastructure.logging import EventLogger
from stock_trading_bot.runtime.portfolio_coordinator import PortfolioCoordinator
from stock_trading_bot.runtime.result_collector import ResultCollector


@dataclass(slots=True, kw_only=True)
class ExecutionCoordinator:
    """Submit orders and route resulting events through state and ledger processing."""

    order_manager: OrderManager
    fill_processor: FillProcessor
    portfolio_coordinator: PortfolioCoordinator
    result_collector: ResultCollector
    event_logger: EventLogger | None = None

    def submit_order(
        self,
        order_request: OrderRequest,
        *,
        market_snapshot: MarketDataSnapshot | None = None,
    ) -> tuple[ProcessedOrderEvent, ...]:
        """Submit one order and fully drain the resulting broker events."""

        snapshot_lookup = (
            {order_request.instrument_id: market_snapshot}
            if market_snapshot is not None
            else {}
        )
        return self.submit_orders(
            (order_request,),
            market_snapshots_by_instrument_id=snapshot_lookup,
        )

    def submit_orders(
        self,
        order_requests: Sequence[OrderRequest],
        *,
        market_snapshots_by_instrument_id: Mapping[str, MarketDataSnapshot] | None = None,
    ) -> tuple[ProcessedOrderEvent, ...]:
        """Submit multiple orders and process broker events until the queue is empty."""

        processed_events: list[ProcessedOrderEvent] = []
        snapshot_lookup = dict(market_snapshots_by_instrument_id or {})

        for order_request in order_requests:
            local_event = self.order_manager.submit_order(order_request)
            processed_events.append(
                self.handle_broker_event(
                    self.normalize_event(local_event),
                    market_price=self._resolve_market_price(order_request, snapshot_lookup),
                )
            )

        while True:
            broker_events = tuple(self.order_manager.poll_broker_events())
            if not broker_events:
                break
            for raw_event in broker_events:
                normalized_event = self.normalize_event(raw_event)
                order_request = self.portfolio_coordinator.get_order_request(
                    normalized_event.order_request_id
                )
                processed_events.append(
                    self.handle_broker_event(
                        normalized_event,
                        market_price=self._resolve_market_price(order_request, snapshot_lookup),
                    )
                )

        return tuple(processed_events)

    def request_cancel(
        self,
        order_request_id: str,
        *,
        market_price: Decimal | None = None,
    ) -> tuple[ProcessedOrderEvent, ...]:
        """Request a cancel and process any resulting broker events."""

        cancel_requested_event = self.order_manager.request_cancel(order_request_id)
        processed_events = [
            self.handle_broker_event(cancel_requested_event, market_price=market_price)
        ]
        for broker_event in self.order_manager.poll_broker_events():
            processed_events.append(
                self.handle_broker_event(
                    self.normalize_event(broker_event),
                    market_price=market_price,
                )
            )
        return tuple(processed_events)

    @staticmethod
    def normalize_event(raw_event: OrderEvent) -> OrderEvent:
        """Normalize a broker event into the project's standard OrderEvent."""

        return raw_event

    def handle_broker_event(
        self,
        raw_event: OrderEvent,
        *,
        market_price: Decimal | None = None,
    ) -> ProcessedOrderEvent:
        """Process one normalized order event and apply its ledger impact."""

        processed_event = self.fill_processor.process_event(
            raw_event,
            market_price=market_price,
        )
        self.portfolio_coordinator.apply_order_event(
            processed_event.order_event,
            market_price=market_price,
        )
        self.result_collector.record_processed_order_event(processed_event)
        if self.event_logger is not None:
            self.event_logger.log_processed_order_event(processed_event)
            self.event_logger.log_portfolio_snapshot(
                processed_order_event=processed_event,
                account_state=self.portfolio_coordinator.current_account_state(),
                positions=self.portfolio_coordinator.current_positions(),
            )
        return processed_event

    @staticmethod
    def _resolve_market_price(
        order_request: OrderRequest,
        market_snapshots_by_instrument_id: Mapping[str, MarketDataSnapshot],
    ) -> Decimal | None:
        snapshot = market_snapshots_by_instrument_id.get(order_request.instrument_id)
        if snapshot is None:
            return None
        return snapshot.open_price
