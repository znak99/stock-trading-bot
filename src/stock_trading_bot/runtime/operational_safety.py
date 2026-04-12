"""Operational trading safety guards."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from stock_trading_bot.core.models import AccountState, OrderRequest, Position
from stock_trading_bot.infrastructure.notifications import AlertNotification


@dataclass(slots=True, frozen=True, kw_only=True)
class AbnormalStateChecks:
    """Configurable abnormal-state detection switches."""

    detect_negative_cash_balance: bool = True
    detect_available_cash_inconsistency: bool = True
    detect_reserved_cash_exceeds_cash_balance: bool = True
    detect_negative_position_quantity: bool = True
    detect_active_position_limit_breach: bool = True


@dataclass(slots=True, frozen=True, kw_only=True)
class OperationalSafetyConfig:
    """Configuration for runtime safety guard behavior."""

    enabled: bool = True
    daily_loss_limit_rate: Decimal = Decimal("0.03")
    block_duplicate_active_orders: bool = True
    halt_on_abnormal_state: bool = True
    allow_exit_orders_during_daily_loss_block: bool = True
    abnormal_state_checks: AbnormalStateChecks = field(default_factory=AbnormalStateChecks)


@dataclass(slots=True, kw_only=True)
class OperationalSafetyGuard:
    """Monitor drawdown and abnormal states, then block unsafe order flow."""

    config: OperationalSafetyConfig = field(default_factory=OperationalSafetyConfig)
    current_trading_date: date | None = field(default=None, init=False)
    day_start_equity: Decimal | None = field(default=None, init=False)
    entry_orders_blocked: bool = field(default=False, init=False)
    all_orders_halted: bool = field(default=False, init=False)
    _emitted_alert_keys: set[str] = field(default_factory=set, init=False)

    def start_trading_day(self, trading_date: date, account_state: AccountState) -> None:
        """Reset day-scoped controls for a new trading date."""

        if not self.config.enabled or self.current_trading_date == trading_date:
            return
        self.current_trading_date = trading_date
        self.day_start_equity = account_state.total_equity
        self.entry_orders_blocked = False
        self._emitted_alert_keys.clear()

    def evaluate_portfolio(
        self,
        *,
        trading_date: date,
        reason: str,
        account_state: AccountState,
        positions: tuple[Position, ...],
    ) -> tuple[AlertNotification, ...]:
        """Evaluate portfolio safety and emit new alerts when needed."""

        if not self.config.enabled:
            return ()

        self.start_trading_day(trading_date, account_state)
        alerts: list[AlertNotification] = []

        if self.config.halt_on_abnormal_state and not self.all_orders_halted:
            abnormalities = self._detect_abnormalities(account_state, positions)
            if abnormalities:
                self.all_orders_halted = True
                alert = self._emit_once(
                    key=f"{trading_date.isoformat()}:abnormal_state_detected",
                    timestamp=account_state.timestamp,
                    severity="critical",
                    code="abnormal_state_detected",
                    title="Abnormal portfolio state detected",
                    message=(
                        "Operational safety halted all orders after detecting "
                        "an inconsistent account or position state."
                    ),
                    metadata={
                        "reason": reason,
                        "trading_date": trading_date.isoformat(),
                        "abnormalities": abnormalities,
                    },
                )
                if alert is not None:
                    alerts.append(alert)

        if (
            not self.all_orders_halted
            and not self.entry_orders_blocked
            and self.day_start_equity is not None
            and self.day_start_equity > Decimal("0")
            and self.config.daily_loss_limit_rate > Decimal("0")
        ):
            daily_drawdown_rate = (
                self.day_start_equity - account_state.total_equity
            ) / self.day_start_equity
            if daily_drawdown_rate >= self.config.daily_loss_limit_rate:
                self.entry_orders_blocked = True
                alert = self._emit_once(
                    key=f"{trading_date.isoformat()}:daily_loss_limit_breached",
                    timestamp=account_state.timestamp,
                    severity="warning",
                    code="daily_loss_limit_breached",
                    title="Daily loss limit breached",
                    message=(
                        "Operational safety blocked new entry orders because the "
                        "daily drawdown limit was exceeded."
                    ),
                    metadata={
                        "reason": reason,
                        "trading_date": trading_date.isoformat(),
                        "day_start_equity": str(self.day_start_equity),
                        "current_equity": str(account_state.total_equity),
                        "daily_drawdown_rate": str(daily_drawdown_rate),
                        "daily_loss_limit_rate": str(self.config.daily_loss_limit_rate),
                    },
                )
                if alert is not None:
                    alerts.append(alert)

        return tuple(alerts)

    def should_allow_order(self, order_request: OrderRequest) -> bool:
        """Return whether an order request may proceed under the current safety state."""

        if not self.config.enabled:
            return True
        if self.all_orders_halted:
            return False
        if not self.entry_orders_blocked:
            return True
        return (
            order_request.side == "sell"
            and self.config.allow_exit_orders_during_daily_loss_block
        )

    def evaluate_duplicate_order(
        self,
        *,
        instrument_id: str,
        side: str,
        timestamp: datetime,
        active_order_exists: bool,
    ) -> tuple[bool, tuple[AlertNotification, ...]]:
        """Block duplicate active orders and emit a single alert for the duplicate key."""

        if (
            not self.config.enabled
            or not self.config.block_duplicate_active_orders
            or not active_order_exists
        ):
            return True, ()

        alert = self._emit_once(
            key=f"duplicate_order_blocked:{instrument_id}:{side}",
            timestamp=timestamp,
            severity="warning",
            code="duplicate_order_blocked",
            title="Duplicate active order blocked",
            message=(
                "Operational safety blocked a duplicate order because an active "
                "order already exists for the same instrument and side."
            ),
            metadata={
                "instrument_id": instrument_id,
                "side": side,
            },
        )
        return False, (() if alert is None else (alert,))

    def _detect_abnormalities(
        self,
        account_state: AccountState,
        positions: tuple[Position, ...],
    ) -> tuple[str, ...]:
        abnormalities: list[str] = []
        checks = self.config.abnormal_state_checks

        if checks.detect_negative_cash_balance and account_state.cash_balance < Decimal("0"):
            abnormalities.append("negative_cash_balance")

        if (
            checks.detect_available_cash_inconsistency
            and account_state.available_cash
            != account_state.cash_balance - account_state.reserved_cash
        ):
            abnormalities.append("available_cash_inconsistency")

        if (
            checks.detect_reserved_cash_exceeds_cash_balance
            and account_state.reserved_cash > account_state.cash_balance
        ):
            abnormalities.append("reserved_cash_exceeds_cash_balance")

        if (
            checks.detect_active_position_limit_breach
            and account_state.active_position_count > account_state.max_position_limit
        ):
            abnormalities.append("active_position_limit_breach")

        if checks.detect_negative_position_quantity:
            for position in positions:
                if position.quantity < Decimal("0"):
                    abnormalities.append(f"negative_position_quantity:{position.instrument_id}")

        return tuple(abnormalities)

    def _emit_once(
        self,
        *,
        key: str,
        timestamp: datetime,
        severity: str,
        code: str,
        title: str,
        message: str,
        metadata: dict[str, Any],
    ) -> AlertNotification | None:
        if key in self._emitted_alert_keys:
            return None
        self._emitted_alert_keys.add(key)
        return AlertNotification.create(
            timestamp=timestamp,
            severity=severity,
            code=code,
            title=title,
            message=message,
            metadata=metadata,
        )
