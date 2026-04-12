"""Portfolio orchestration for risk checks, reservations, and mark-to-market updates."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, Decimal

from stock_trading_bot.core.models import (
    AccountState,
    MarketDataSnapshot,
    OrderEvent,
    OrderRequest,
    Position,
    RiskCheckResult,
    ScoreResult,
    Signal,
)
from stock_trading_bot.portfolio import (
    AccountStateStore,
    EqualWeightAllocationPolicy,
    PortfolioUpdater,
    PositionBook,
    PreTradeRiskChecker,
)

FRACTION_PATTERN = re.compile(r"fraction=([0-9]+(?:\.[0-9]+)?)")


@dataclass(slots=True, kw_only=True)
class PortfolioCoordinator:
    """Coordinate risk checks, next-open reservations, and portfolio updates."""

    position_book: PositionBook
    account_state_store: AccountStateStore
    risk_checker: PreTradeRiskChecker
    portfolio_updater: PortfolioUpdater
    allocation_policy: EqualWeightAllocationPolicy
    broker_mode: str
    order_type: str = "market"
    time_in_force: str = "day"
    lot_size: Decimal = Decimal("1")
    default_partial_sell_fraction: Decimal = Decimal("0.5")
    _scheduled_order_ids_by_date: dict[date, list[str]] = field(default_factory=dict, init=False)
    _order_requests_by_id: dict[str, OrderRequest] = field(default_factory=dict, init=False)
    _signals_by_id: dict[str, Signal] = field(default_factory=dict, init=False)
    _risk_results_by_order_request_id: dict[str, RiskCheckResult] = field(
        default_factory=dict,
        init=False,
    )
    _partial_take_profit_instrument_ids: set[str] = field(default_factory=set, init=False)

    def build_order_request(
        self,
        signal: Signal,
        *,
        snapshot: MarketDataSnapshot,
        score_result: ScoreResult | None = None,
    ) -> OrderRequest | None:
        """Build a risk-checked order request from a strategy signal."""

        side = "buy" if signal.signal_type == "buy" else "sell"
        requested_quantity = self._resolve_requested_quantity(signal, snapshot)
        if requested_quantity <= Decimal("0"):
            return None

        provisional_order_request = OrderRequest(
            order_request_id=f"order:{signal.signal_id}",
            instrument_id=signal.instrument_id,
            timestamp=signal.target_execution_time,
            side=side,
            order_type=self.order_type,
            quantity=requested_quantity,
            price=snapshot.close_price,
            time_in_force=self.time_in_force,
            source_signal_id=signal.signal_id,
            risk_check_ref="pending",
            broker_mode=self.broker_mode,
            request_reason=self._build_request_reason(signal, score_result),
        )

        risk_check_result = self.risk_checker.check_order(
            provisional_order_request,
            self.account_state_store.get_state(),
            self.position_book,
        )
        if not risk_check_result.passed:
            adjusted_quantity = min(requested_quantity, risk_check_result.allowed_quantity)
            if adjusted_quantity <= Decimal("0"):
                return None

            provisional_order_request = OrderRequest(
                order_request_id=provisional_order_request.order_request_id,
                instrument_id=provisional_order_request.instrument_id,
                timestamp=provisional_order_request.timestamp,
                side=provisional_order_request.side,
                order_type=provisional_order_request.order_type,
                quantity=adjusted_quantity,
                price=provisional_order_request.price,
                time_in_force=provisional_order_request.time_in_force,
                source_signal_id=provisional_order_request.source_signal_id,
                risk_check_ref=provisional_order_request.risk_check_ref,
                broker_mode=provisional_order_request.broker_mode,
                request_reason=provisional_order_request.request_reason,
            )
            risk_check_result = self.risk_checker.check_order(
                provisional_order_request,
                self.account_state_store.get_state(),
                self.position_book,
            )
            if not risk_check_result.passed:
                return None

        final_quantity = min(requested_quantity, risk_check_result.allowed_quantity)
        if final_quantity <= Decimal("0"):
            return None

        order_request = OrderRequest(
            order_request_id=provisional_order_request.order_request_id,
            instrument_id=provisional_order_request.instrument_id,
            timestamp=provisional_order_request.timestamp,
            side=provisional_order_request.side,
            order_type=provisional_order_request.order_type,
            quantity=final_quantity,
            price=provisional_order_request.price,
            time_in_force=provisional_order_request.time_in_force,
            source_signal_id=provisional_order_request.source_signal_id,
            risk_check_ref=risk_check_result.risk_check_id,
            broker_mode=provisional_order_request.broker_mode,
            request_reason=provisional_order_request.request_reason,
        )

        self._order_requests_by_id[order_request.order_request_id] = order_request
        self._signals_by_id[signal.signal_id] = signal
        self._risk_results_by_order_request_id[order_request.order_request_id] = risk_check_result
        return order_request

    def schedule_next_open_orders(
        self,
        signals: Sequence[Signal],
        *,
        snapshots_by_instrument_id: Mapping[str, MarketDataSnapshot],
        scores_by_candidate_ref: Mapping[str, ScoreResult] | None = None,
    ) -> tuple[OrderRequest, ...]:
        """Convert confirmed signals into reserved next-open orders."""

        scheduled_order_requests: list[OrderRequest] = []
        score_lookup = dict(scores_by_candidate_ref or {})

        for signal in signals:
            snapshot = snapshots_by_instrument_id.get(signal.instrument_id)
            if snapshot is None:
                continue
            order_request = self.build_order_request(
                signal,
                snapshot=snapshot,
                score_result=score_lookup.get(signal.candidate_ref),
            )
            if order_request is None:
                continue

            if order_request.side == "buy":
                self.portfolio_updater.reserve_for_buy(order_request)
            else:
                self.portfolio_updater.reserve_for_sell(order_request)

            execution_date = order_request.timestamp.date()
            self._scheduled_order_ids_by_date.setdefault(execution_date, []).append(
                order_request.order_request_id
            )
            scheduled_order_requests.append(order_request)

        return tuple(scheduled_order_requests)

    def pop_scheduled_orders(self, execution_date: date) -> tuple[OrderRequest, ...]:
        """Return and remove orders scheduled for the provided trading date."""

        order_request_ids = self._scheduled_order_ids_by_date.pop(execution_date, [])
        scheduled_orders = [
            self._order_requests_by_id[order_request_id]
            for order_request_id in order_request_ids
        ]
        scheduled_orders.sort(key=lambda order_request: 0 if order_request.side == "sell" else 1)
        return tuple(scheduled_orders)

    def get_order_request(self, order_request_id: str) -> OrderRequest:
        """Return a tracked order request by identifier."""

        try:
            return self._order_requests_by_id[order_request_id]
        except KeyError as error:
            raise ValueError(f"Unknown order_request_id={order_request_id!r}.") from error

    def apply_order_event(
        self,
        order_event: OrderEvent,
        *,
        market_price: Decimal | None = None,
    ) -> None:
        """Apply a processed order event to the underlying portfolio updater."""

        order_request = self.get_order_request(order_event.order_request_id)
        self.portfolio_updater.apply_order_event(
            order_request,
            order_event,
            market_price=market_price,
        )

        signal = self._signals_by_id.get(order_request.source_signal_id)
        if (
            signal is not None
            and signal.signal_type == "partial_sell"
            and order_event.filled_quantity > Decimal("0")
        ):
            self._partial_take_profit_instrument_ids.add(order_request.instrument_id)

    def has_partial_take_profit(self, position: Position) -> bool:
        """Return whether the position has already taken a partial profit."""

        return position.instrument_id in self._partial_take_profit_instrument_ids

    def mark_to_market(
        self,
        snapshots_by_instrument_id: Mapping[str, MarketDataSnapshot],
        *,
        timestamp: datetime | None = None,
    ) -> None:
        """Refresh open positions and account summary using the latest snapshots."""

        for position in self.position_book.open_positions():
            snapshot = snapshots_by_instrument_id.get(position.instrument_id)
            if snapshot is None:
                continue

            position.current_price = snapshot.close_price
            position.updated_at = snapshot.timestamp
            position.unrealized_pnl = (
                (position.current_price - position.avg_entry_price) * position.quantity
            )
            position.unrealized_pnl_rate = (
                Decimal("0")
                if position.avg_entry_price == Decimal("0")
                else (position.current_price - position.avg_entry_price) / position.avg_entry_price
            )
            self.position_book.upsert(position)

        self.account_state_store.update_timestamp(
            timestamp or self._resolve_latest_timestamp(snapshots_by_instrument_id)
        )
        self.account_state_store.recalculate_summary(self.position_book)

    def current_account_state(self) -> AccountState:
        """Return the latest account state."""

        return self.account_state_store.get_state()

    def current_positions(self) -> tuple[Position, ...]:
        """Return all tracked positions."""

        return self.position_book.all_positions()

    def open_positions(self) -> tuple[Position, ...]:
        """Return open positions only."""

        return self.position_book.open_positions()

    def _resolve_requested_quantity(
        self,
        signal: Signal,
        snapshot: MarketDataSnapshot,
    ) -> Decimal:
        if signal.signal_type == "buy":
            capital_budget = self.allocation_policy.target_capital(
                self.account_state_store.get_state()
            )
            return self.allocation_policy.quantity_for_capital(snapshot.close_price, capital_budget)

        position = self.position_book.get(signal.instrument_id)
        if position is None or position.position_status != "open":
            return Decimal("0")

        if signal.signal_type == "sell":
            return position.quantity

        fraction = self._parse_partial_sell_fraction(signal.decision_reason)
        raw_quantity = position.quantity * fraction
        lot_count = (raw_quantity / self.lot_size).to_integral_value(rounding=ROUND_DOWN)
        quantity = lot_count * self.lot_size
        if quantity == Decimal("0") and position.quantity > Decimal("0"):
            return min(self.lot_size, position.quantity)
        return min(quantity, position.quantity)

    def _build_request_reason(
        self,
        signal: Signal,
        score_result: ScoreResult | None,
    ) -> str:
        if score_result is None:
            return signal.decision_reason
        return (
            f"{signal.decision_reason}; "
            f"score_model={score_result.model_name}; "
            f"score_value={score_result.score_value}; "
            f"score_rank={score_result.rank}"
        )

    def _parse_partial_sell_fraction(self, decision_reason: str) -> Decimal:
        matched_fraction = FRACTION_PATTERN.search(decision_reason)
        if matched_fraction is None:
            return self.default_partial_sell_fraction
        return Decimal(matched_fraction.group(1))

    @staticmethod
    def _resolve_latest_timestamp(
        snapshots_by_instrument_id: Mapping[str, MarketDataSnapshot],
    ) -> datetime:
        if not snapshots_by_instrument_id:
            return datetime.now(tz=UTC)
        return max(snapshot.timestamp for snapshot in snapshots_by_instrument_id.values())
