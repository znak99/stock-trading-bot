"""Portfolio update logic driven by execution events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from stock_trading_bot.core.enums import OrderEventType
from stock_trading_bot.core.models import AccountState, OrderEvent, OrderRequest, Position
from stock_trading_bot.portfolio.stores import AccountStateStore, PositionBook


@dataclass(slots=True, kw_only=True)
class CostProfile:
    """Cost configuration used by the portfolio updater."""

    buy_commission_rate: Decimal = Decimal("0.00025")
    sell_commission_rate: Decimal = Decimal("0.00025")
    sell_tax_rate: Decimal = Decimal("0.0020")
    buy_slippage_rate: Decimal = Decimal("0.0030")
    sell_slippage_rate: Decimal = Decimal("0.0015")

    def estimate_buy_cash_requirement(self, reference_price: Decimal, quantity: Decimal) -> Decimal:
        """Estimate required reserved cash for a buy order."""

        effective_buy_price = reference_price * (Decimal("1") + self.buy_slippage_rate)
        gross_buy_amount = effective_buy_price * quantity
        buy_commission = gross_buy_amount * self.buy_commission_rate
        return gross_buy_amount + buy_commission


@dataclass(slots=True, kw_only=True)
class _TrackedOrder:
    order_request: OrderRequest
    reserved_cash_remaining: Decimal = Decimal("0")
    reserved_sell_quantity_remaining: Decimal = Decimal("0")
    last_filled_quantity: Decimal = Decimal("0")
    last_filled_price_avg: Decimal = Decimal("0")


class PortfolioUpdater:
    """Apply order reservations and fill events to account and position state."""

    def __init__(
        self,
        *,
        position_book: PositionBook,
        account_state_store: AccountStateStore,
        cost_profile: CostProfile | None = None,
        default_exit_policy_name: str = "conservative_exit_policy",
    ) -> None:
        self._position_book = position_book
        self._account_state_store = account_state_store
        self._cost_profile = cost_profile or CostProfile()
        self._default_exit_policy_name = default_exit_policy_name
        self._tracked_orders: dict[str, _TrackedOrder] = {}

    def reserve_for_buy(
        self,
        order_request: OrderRequest,
        reference_price: Decimal | None = None,
    ) -> None:
        """Reserve cash for a pending buy order."""

        reference = reference_price or order_request.price
        reserved_cash = self._cost_profile.estimate_buy_cash_requirement(
            reference,
            order_request.quantity,
        )
        account_state = self._account_state_store.get_state()
        if reserved_cash > account_state.available_cash:
            raise ValueError("Insufficient available cash to reserve for buy order.")

        self._account_state_store.increase_reserved_cash(reserved_cash)
        self._track_order(
            order_request,
            reserved_cash_remaining=reserved_cash,
            reserved_sell_quantity_remaining=Decimal("0"),
        )

    def reserve_for_sell(self, order_request: OrderRequest) -> None:
        """Reserve sellable quantity for a pending sell order."""

        position = self._position_book.get(order_request.instrument_id)
        if position is None or position.position_status != "open":
            raise ValueError("Cannot reserve sell quantity without an open position.")

        account_state = self._account_state_store.get_state()
        reserved_quantity = account_state.reserved_sell_quantity.get(
            order_request.instrument_id,
            Decimal("0"),
        )
        tradable_quantity = position.quantity - reserved_quantity
        if order_request.quantity > tradable_quantity:
            raise ValueError("Insufficient tradable quantity to reserve for sell order.")

        account_state.reserved_sell_quantity[order_request.instrument_id] = (
            reserved_quantity + order_request.quantity
        )
        self._track_order(
            order_request,
            reserved_cash_remaining=Decimal("0"),
            reserved_sell_quantity_remaining=order_request.quantity,
        )

    def apply_order_event(
        self,
        order_request: OrderRequest,
        order_event: OrderEvent,
        *,
        market_price: Decimal | None = None,
    ) -> None:
        """Apply an execution event to the portfolio state."""

        tracked_order = self._tracked_orders.get(order_request.order_request_id)
        if tracked_order is None:
            tracked_order = self._track_order(
                order_request,
                reserved_cash_remaining=Decimal("0"),
                reserved_sell_quantity_remaining=Decimal("0"),
            )

        event_type = OrderEventType(order_event.event_type)
        delta_fill_quantity, delta_raw_fill_price = self._resolve_delta_fill(
            order_event,
            tracked_order,
        )

        if delta_fill_quantity > Decimal("0"):
            if order_request.side == "buy":
                self._apply_buy_fill(
                    tracked_order,
                    order_event,
                    delta_fill_quantity,
                    delta_raw_fill_price,
                    market_price=market_price,
                )
            else:
                self._apply_sell_fill(
                    tracked_order,
                    order_event,
                    delta_fill_quantity,
                    delta_raw_fill_price,
                    market_price=market_price,
                )

        tracked_order.last_filled_quantity = order_event.filled_quantity
        tracked_order.last_filled_price_avg = order_event.filled_price_avg

        if event_type in {
            OrderEventType.BROKER_REJECTED,
            OrderEventType.INTERNAL_REJECTED,
            OrderEventType.CANCELED_BEFORE_SUBMIT,
            OrderEventType.CANCEL_CONFIRMED,
            OrderEventType.EXPIRED,
        } or event_type == OrderEventType.FULL_FILL or order_event.is_terminal:
            self._release_remaining_reservations(tracked_order)

        self._account_state_store.update_timestamp(order_event.timestamp)
        self._account_state_store.recalculate_summary(self._position_book)

    def release_order_reservation(
        self,
        order_request_id: str,
        *,
        timestamp: datetime | None = None,
    ) -> None:
        """Release any remaining reservation for an order that will not be submitted."""

        tracked_order = self._tracked_orders.get(order_request_id)
        if tracked_order is None:
            return

        self._release_remaining_reservations(tracked_order)
        self._account_state_store.update_timestamp(
            timestamp or self._account_state_store.get_state().timestamp
        )
        self._account_state_store.recalculate_summary(self._position_book)

    def _apply_buy_fill(
        self,
        tracked_order: _TrackedOrder,
        order_event: OrderEvent,
        delta_fill_quantity: Decimal,
        delta_raw_fill_price: Decimal,
        *,
        market_price: Decimal | None,
    ) -> None:
        account_state = self._account_state_store.get_state()
        effective_buy_price = delta_raw_fill_price * (
            Decimal("1") + self._cost_profile.buy_slippage_rate
        )
        gross_buy_amount = effective_buy_price * delta_fill_quantity
        buy_commission = gross_buy_amount * self._cost_profile.buy_commission_rate
        total_buy_cash = gross_buy_amount + buy_commission

        account_state.cash_balance -= total_buy_cash
        account_state.accumulated_buy_commission += buy_commission
        account_state.accumulated_slippage_cost_estimate += (
            effective_buy_price - delta_raw_fill_price
        ) * delta_fill_quantity

        reserved_cash_release = min(
            tracked_order.reserved_cash_remaining,
            total_buy_cash,
        )
        tracked_order.reserved_cash_remaining -= reserved_cash_release
        self._account_state_store.decrease_reserved_cash(reserved_cash_release)

        position = self._position_book.get(tracked_order.order_request.instrument_id)
        if position is None or position.position_status != "open":
            position = Position(
                position_id=f"position:{tracked_order.order_request.instrument_id}",
                instrument_id=tracked_order.order_request.instrument_id,
                opened_at=order_event.timestamp,
                updated_at=order_event.timestamp,
                quantity=Decimal("0"),
                avg_entry_price=Decimal("0"),
                current_price=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                unrealized_pnl_rate=Decimal("0"),
                position_status="closed",
                exit_policy_name=self._default_exit_policy_name,
            )

        existing_quantity = position.quantity
        new_quantity = existing_quantity + delta_fill_quantity
        new_avg_entry_price = (
            (existing_quantity * position.avg_entry_price)
            + (delta_fill_quantity * effective_buy_price)
        ) / new_quantity
        current_price = market_price or effective_buy_price

        position.quantity = new_quantity
        position.avg_entry_price = new_avg_entry_price
        position.current_price = current_price
        position.unrealized_pnl = (current_price - new_avg_entry_price) * new_quantity
        position.unrealized_pnl_rate = (
            Decimal("0")
            if new_avg_entry_price == Decimal("0")
            else (current_price - new_avg_entry_price) / new_avg_entry_price
        )
        position.position_status = "open"
        position.updated_at = order_event.timestamp
        if existing_quantity == Decimal("0"):
            position.opened_at = order_event.timestamp

        self._position_book.upsert(position)

    def _apply_sell_fill(
        self,
        tracked_order: _TrackedOrder,
        order_event: OrderEvent,
        delta_fill_quantity: Decimal,
        delta_raw_fill_price: Decimal,
        *,
        market_price: Decimal | None,
    ) -> None:
        position = self._position_book.get(tracked_order.order_request.instrument_id)
        if position is None or position.position_status != "open":
            raise ValueError("Cannot apply sell fill without an open position.")
        if delta_fill_quantity > position.quantity:
            raise ValueError("Sell fill quantity exceeds the current position quantity.")

        account_state = self._account_state_store.get_state()
        effective_sell_price = delta_raw_fill_price * (
            Decimal("1") - self._cost_profile.sell_slippage_rate
        )
        gross_sell_amount = effective_sell_price * delta_fill_quantity
        sell_commission = gross_sell_amount * self._cost_profile.sell_commission_rate
        sell_tax = gross_sell_amount * self._cost_profile.sell_tax_rate
        net_sell_cash_inflow = gross_sell_amount - sell_commission - sell_tax

        account_state.cash_balance += net_sell_cash_inflow
        account_state.realized_pnl += (
            (effective_sell_price - position.avg_entry_price) * delta_fill_quantity
        ) - sell_commission - sell_tax
        account_state.accumulated_sell_commission += sell_commission
        account_state.accumulated_sell_tax += sell_tax
        account_state.accumulated_slippage_cost_estimate += (
            delta_raw_fill_price - effective_sell_price
        ) * delta_fill_quantity

        reserved_quantity_release = min(
            tracked_order.reserved_sell_quantity_remaining,
            delta_fill_quantity,
        )
        tracked_order.reserved_sell_quantity_remaining -= reserved_quantity_release
        current_reserved_quantity = account_state.reserved_sell_quantity.get(
            tracked_order.order_request.instrument_id,
            Decimal("0"),
        )
        new_reserved_quantity = max(
            Decimal("0"),
            current_reserved_quantity - reserved_quantity_release,
        )
        if new_reserved_quantity == Decimal("0"):
            account_state.reserved_sell_quantity.pop(
                tracked_order.order_request.instrument_id,
                None,
            )
        else:
            account_state.reserved_sell_quantity[
                tracked_order.order_request.instrument_id
            ] = new_reserved_quantity

        position.quantity -= delta_fill_quantity
        position.current_price = market_price or effective_sell_price
        position.updated_at = order_event.timestamp
        if position.quantity == Decimal("0"):
            position.position_status = "closed"
            position.unrealized_pnl = Decimal("0")
            position.unrealized_pnl_rate = Decimal("0")
        else:
            position.position_status = "open"
            position.unrealized_pnl = (
                position.current_price - position.avg_entry_price
            ) * position.quantity
            position.unrealized_pnl_rate = (
                Decimal("0")
                if position.avg_entry_price == Decimal("0")
                else (position.current_price - position.avg_entry_price) / position.avg_entry_price
            )

        self._position_book.upsert(position)

    def _release_remaining_reservations(self, tracked_order: _TrackedOrder) -> None:
        account_state = self._account_state_store.get_state()

        if tracked_order.reserved_cash_remaining > Decimal("0"):
            self._account_state_store.decrease_reserved_cash(tracked_order.reserved_cash_remaining)
            tracked_order.reserved_cash_remaining = Decimal("0")

        if tracked_order.reserved_sell_quantity_remaining > Decimal("0"):
            current_reserved_quantity = account_state.reserved_sell_quantity.get(
                tracked_order.order_request.instrument_id,
                Decimal("0"),
            )
            new_reserved_quantity = max(
                Decimal("0"),
                current_reserved_quantity - tracked_order.reserved_sell_quantity_remaining,
            )
            if new_reserved_quantity == Decimal("0"):
                account_state.reserved_sell_quantity.pop(
                    tracked_order.order_request.instrument_id,
                    None,
                )
            else:
                account_state.reserved_sell_quantity[tracked_order.order_request.instrument_id] = (
                    new_reserved_quantity
                )
            tracked_order.reserved_sell_quantity_remaining = Decimal("0")

    def _resolve_delta_fill(
        self,
        order_event: OrderEvent,
        tracked_order: _TrackedOrder,
    ) -> tuple[Decimal, Decimal]:
        current_filled_quantity = order_event.filled_quantity
        if current_filled_quantity < tracked_order.last_filled_quantity:
            raise ValueError("Order event cumulative fill quantity cannot move backwards.")

        delta_fill_quantity = current_filled_quantity - tracked_order.last_filled_quantity
        if delta_fill_quantity == Decimal("0"):
            return Decimal("0"), Decimal("0")

        previous_notional = tracked_order.last_filled_quantity * tracked_order.last_filled_price_avg
        current_notional = current_filled_quantity * order_event.filled_price_avg
        delta_raw_fill_notional = current_notional - previous_notional
        if delta_raw_fill_notional < Decimal("0"):
            raise ValueError("Order event cumulative notional cannot move backwards.")

        return delta_fill_quantity, delta_raw_fill_notional / delta_fill_quantity

    def _track_order(
        self,
        order_request: OrderRequest,
        *,
        reserved_cash_remaining: Decimal,
        reserved_sell_quantity_remaining: Decimal,
    ) -> _TrackedOrder:
        tracked_order = _TrackedOrder(
            order_request=order_request,
            reserved_cash_remaining=reserved_cash_remaining,
            reserved_sell_quantity_remaining=reserved_sell_quantity_remaining,
        )
        self._tracked_orders[order_request.order_request_id] = tracked_order
        return tracked_order


def build_initial_account_state(
    *,
    account_state_id: str,
    broker_mode: str,
    cash_balance: Decimal,
    max_position_limit: int,
    timestamp: datetime | None = None,
) -> AccountState:
    """Helper to create an empty initial account state."""

    account_timestamp = timestamp or datetime.now(tz=UTC)
    return AccountState(
        account_state_id=account_state_id,
        timestamp=account_timestamp,
        broker_mode=broker_mode,
        total_equity=cash_balance,
        cash_balance=cash_balance,
        available_cash=cash_balance,
        market_value=Decimal("0"),
        active_position_count=0,
        max_position_limit=max_position_limit,
        account_status="active",
    )
