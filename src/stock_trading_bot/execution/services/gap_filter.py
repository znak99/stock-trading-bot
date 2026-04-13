"""Next-open gap filter for entry orders."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from stock_trading_bot.core.models import MarketDataSnapshot, OrderRequest


@dataclass(slots=True, frozen=True, kw_only=True)
class GapFilterDecision:
    """Decision result for one next-open gap-filter evaluation."""

    order_request_id: str
    instrument_id: str
    allowed: bool
    reason: str
    gap_rate: Decimal | None
    previous_close: Decimal | None
    open_price: Decimal


@dataclass(slots=True, kw_only=True)
class GapFilterPolicy:
    """Filter large next-open gaps before submitting new entry orders."""

    enabled: bool = False
    block_gap_up: bool = True
    max_gap_up_rate: Decimal = Decimal("0.05")
    block_gap_down: bool = False
    min_gap_down_rate: Decimal = Decimal("-0.06")

    def evaluate(
        self,
        order_request: OrderRequest,
        *,
        open_snapshot: MarketDataSnapshot,
        previous_close: Decimal | None,
    ) -> GapFilterDecision:
        """Return whether the order should remain eligible for submission."""

        if not self.enabled or order_request.side != "buy":
            return GapFilterDecision(
                order_request_id=order_request.order_request_id,
                instrument_id=order_request.instrument_id,
                allowed=True,
                reason="gap_filter_not_applicable",
                gap_rate=None,
                previous_close=previous_close,
                open_price=open_snapshot.open_price,
            )

        if previous_close in {None, Decimal("0")}:
            return GapFilterDecision(
                order_request_id=order_request.order_request_id,
                instrument_id=order_request.instrument_id,
                allowed=True,
                reason="previous_close_unavailable",
                gap_rate=None,
                previous_close=previous_close,
                open_price=open_snapshot.open_price,
            )

        gap_rate = (open_snapshot.open_price / previous_close) - Decimal("1")
        if self.block_gap_up and gap_rate > self.max_gap_up_rate:
            return GapFilterDecision(
                order_request_id=order_request.order_request_id,
                instrument_id=order_request.instrument_id,
                allowed=False,
                reason=(
                    "blocked_gap_up("
                    f"gap_rate={gap_rate},max_gap_up_rate={self.max_gap_up_rate})"
                ),
                gap_rate=gap_rate,
                previous_close=previous_close,
                open_price=open_snapshot.open_price,
            )
        if self.block_gap_down and gap_rate < self.min_gap_down_rate:
            return GapFilterDecision(
                order_request_id=order_request.order_request_id,
                instrument_id=order_request.instrument_id,
                allowed=False,
                reason=(
                    "blocked_gap_down("
                    f"gap_rate={gap_rate},min_gap_down_rate={self.min_gap_down_rate})"
                ),
                gap_rate=gap_rate,
                previous_close=previous_close,
                open_price=open_snapshot.open_price,
            )
        return GapFilterDecision(
            order_request_id=order_request.order_request_id,
            instrument_id=order_request.instrument_id,
            allowed=True,
            reason="gap_filter_passed",
            gap_rate=gap_rate,
            previous_close=previous_close,
            open_price=open_snapshot.open_price,
        )
