"""Broker interface contract."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from stock_trading_bot.core.models import OrderEvent, OrderRequest


@runtime_checkable
class Broker(Protocol):
    """Execution-facing broker contract."""

    mode: str

    def submit_order(self, order_request: OrderRequest) -> str:
        """Submit an order request to a broker and return its broker order id."""

    def cancel_order(self, order_request_id: str) -> None:
        """Request cancellation for a previously submitted order."""

    def poll_events(self) -> Sequence[OrderEvent]:
        """Return normalized or raw-translated execution events ready for processing."""

