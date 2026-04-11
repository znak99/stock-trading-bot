"""Risk check result contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(slots=True, kw_only=True)
class RiskCheckResult:
    """Pre-trade risk validation outcome."""

    risk_check_id: str
    timestamp: datetime
    instrument_id: str
    order_request_preview: dict[str, Any]
    risk_policy_name: str
    passed: bool
    allowed_quantity: Decimal
    allowed_capital: Decimal
    account_state_ref: str
    failure_reasons: tuple[str, ...] = field(default_factory=tuple)
    position_refs: tuple[str, ...] = field(default_factory=tuple)

