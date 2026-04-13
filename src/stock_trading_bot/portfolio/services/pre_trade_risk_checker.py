"""Pre-trade risk checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal

from stock_trading_bot.core.models import AccountState, OrderRequest, RiskCheckResult
from stock_trading_bot.portfolio.policies import AllocationPolicy, EqualWeightAllocationPolicy
from stock_trading_bot.portfolio.stores import PositionBook


@dataclass(slots=True, kw_only=True)
class PreTradeRiskChecker:
    """Validate an order request before it reaches execution."""

    risk_policy_name: str = "conservative_risk_v1"
    max_active_positions: int = 5
    max_position_ratio: Decimal = Decimal("0.20")
    max_single_order_ratio: Decimal = Decimal("0.20")
    block_duplicate_long_entry: bool = True
    min_available_cash_after_order: Decimal = Decimal("0")
    buy_commission_rate: Decimal = Decimal("0.00025")
    buy_slippage_rate: Decimal = Decimal("0.0030")
    allocation_policy: AllocationPolicy = field(
        default_factory=lambda: EqualWeightAllocationPolicy(max_position_ratio=Decimal("0.20"))
    )

    def __post_init__(self) -> None:
        """Keep allocation policy aligned with the configured max position ratio."""

        self.allocation_policy.max_position_ratio = self.max_position_ratio

    def check_order(
        self,
        order_request: OrderRequest,
        account_state: AccountState,
        position_book: PositionBook,
    ) -> RiskCheckResult:
        """Return the pre-trade risk evaluation for an order request."""

        failure_reasons: list[str] = []
        position = position_book.get(order_request.instrument_id)
        position_refs = position_book.position_refs(order_request.instrument_id)

        if order_request.side == "buy":
            allowed_capital, allowed_quantity = self._evaluate_buy_capacity(
                account_state,
                order_request,
            )
            if (
                position is not None
                and position.position_status == "open"
                and self.block_duplicate_long_entry
            ):
                failure_reasons.append("duplicate_long_entry_blocked")

            if (position is None or position.position_status != "open") and (
                position_book.active_position_count() >= self.max_active_positions
            ):
                failure_reasons.append("max_active_positions_reached")

            if order_request.price <= Decimal("0"):
                failure_reasons.append("invalid_order_price")

            if order_request.quantity <= Decimal("0"):
                failure_reasons.append("invalid_order_quantity")

            if allowed_quantity <= Decimal("0"):
                failure_reasons.append("insufficient_available_cash")
            elif order_request.quantity > allowed_quantity:
                failure_reasons.append("requested_quantity_exceeds_allowed_quantity")
        else:
            allowed_capital, allowed_quantity = self._evaluate_sell_capacity(
                account_state,
                order_request,
                position_book,
            )

            if position is None or position.position_status != "open":
                failure_reasons.append("no_open_position_for_sell")

            if order_request.quantity <= Decimal("0"):
                failure_reasons.append("invalid_order_quantity")

            if allowed_quantity <= Decimal("0"):
                failure_reasons.append("no_tradable_sell_quantity")
            elif order_request.quantity > allowed_quantity:
                failure_reasons.append("requested_quantity_exceeds_tradable_sell_quantity")

        return RiskCheckResult(
            risk_check_id=f"risk-{order_request.order_request_id}",
            timestamp=order_request.timestamp,
            instrument_id=order_request.instrument_id,
            order_request_preview=asdict(order_request),
            risk_policy_name=self.risk_policy_name,
            passed=not failure_reasons,
            failure_reasons=tuple(failure_reasons),
            allowed_quantity=allowed_quantity,
            allowed_capital=allowed_capital,
            account_state_ref=account_state.account_state_id,
            position_refs=position_refs,
        )

    def _evaluate_buy_capacity(
        self,
        account_state: AccountState,
        order_request: OrderRequest,
    ) -> tuple[Decimal, Decimal]:
        available_cash_budget = max(
            Decimal("0"),
            account_state.available_cash - self.min_available_cash_after_order,
        )
        equity_budget = account_state.total_equity * self.max_single_order_ratio
        target_budget = self.allocation_policy.target_capital(account_state)
        capital_budget = min(available_cash_budget, equity_budget, target_budget)

        estimated_unit_cash = self._estimate_buy_unit_cash(order_request.price)
        allowed_quantity = self.allocation_policy.quantity_for_capital(
            estimated_unit_cash,
            capital_budget,
        )
        return capital_budget, allowed_quantity

    def _evaluate_sell_capacity(
        self,
        account_state: AccountState,
        order_request: OrderRequest,
        position_book: PositionBook,
    ) -> tuple[Decimal, Decimal]:
        position = position_book.get(order_request.instrument_id)
        if position is None or position.position_status != "open":
            return Decimal("0"), Decimal("0")

        reserved_quantity = account_state.reserved_sell_quantity.get(
            order_request.instrument_id,
            Decimal("0"),
        )
        tradable_quantity = max(Decimal("0"), position.quantity - reserved_quantity)
        allowed_capital = max(Decimal("0"), tradable_quantity * order_request.price)
        return allowed_capital, tradable_quantity

    def _estimate_buy_unit_cash(self, reference_price: Decimal) -> Decimal:
        effective_buy_price = reference_price * (Decimal("1") + self.buy_slippage_rate)
        return effective_buy_price * (Decimal("1") + self.buy_commission_rate)
