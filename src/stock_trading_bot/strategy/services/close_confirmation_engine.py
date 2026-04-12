"""Close confirmation rules for breakout swing entries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from stock_trading_bot.core.models import MarketDataSnapshot
from stock_trading_bot.market.services import EnrichedHistoricalBar, HistoricalOhlcvBar


HistoricalBar = HistoricalOhlcvBar | EnrichedHistoricalBar


@dataclass(slots=True, frozen=True, kw_only=True)
class CloseConfirmationResult:
    """Close-confirmation outcome for a breakout candidate."""

    passed: bool
    reasons: tuple[str, ...]
    lookback_high: Decimal | None
    average_volume: Decimal | None
    volume_ratio: Decimal | None
    close_strength_ratio: Decimal


class CloseConfirmationEngine:
    """Confirm whether a candidate still satisfies breakout conditions at the close."""

    def __init__(
        self,
        *,
        breakout_lookback_days: int,
        volume_ratio_min: Decimal,
        volume_ratio_target: Decimal,
        close_strength_min: Decimal,
        close_must_hold_recent_high: bool = True,
    ) -> None:
        if breakout_lookback_days <= 0:
            raise ValueError("breakout_lookback_days must be positive.")
        if volume_ratio_min <= Decimal("0"):
            raise ValueError("volume_ratio_min must be positive.")
        if volume_ratio_target < volume_ratio_min:
            raise ValueError("volume_ratio_target must be greater than or equal to volume_ratio_min.")
        if close_strength_min <= Decimal("0") or close_strength_min > Decimal("1"):
            raise ValueError("close_strength_min must be between 0 and 1.")

        self.breakout_lookback_days = breakout_lookback_days
        self.volume_ratio_min = volume_ratio_min
        self.volume_ratio_target = volume_ratio_target
        self.close_strength_min = close_strength_min
        self.close_must_hold_recent_high = close_must_hold_recent_high

    def confirm(
        self,
        snapshot: MarketDataSnapshot,
        recent_bars: Sequence[HistoricalBar],
    ) -> CloseConfirmationResult:
        """Return whether the closing snapshot confirms the breakout."""

        prior_bars = tuple(
            bar
            for bar in sorted(recent_bars, key=lambda current_bar: current_bar.timestamp)
            if bar.timestamp < snapshot.timestamp
        )
        if len(prior_bars) < self.breakout_lookback_days:
            return CloseConfirmationResult(
                passed=False,
                reasons=("insufficient_breakout_history",),
                lookback_high=None,
                average_volume=None,
                volume_ratio=None,
                close_strength_ratio=self._calculate_close_strength_ratio(snapshot),
            )

        lookback_window = prior_bars[-self.breakout_lookback_days :]
        lookback_high = max(bar.high_price for bar in lookback_window)
        average_volume = (
            sum((Decimal(bar.volume) for bar in lookback_window), Decimal("0"))
            / Decimal(self.breakout_lookback_days)
        )
        volume_ratio = (
            Decimal(snapshot.volume) / average_volume
            if average_volume > Decimal("0")
            else Decimal("0")
        )
        close_strength_ratio = self._calculate_close_strength_ratio(snapshot)

        reasons: list[str] = []
        price_condition_passed = (
            not self.close_must_hold_recent_high or snapshot.close_price >= lookback_high
        )
        if not self.close_must_hold_recent_high:
            reasons.append("recent_high_check_skipped")
        elif price_condition_passed:
            reasons.append(f"close_above_recent_high(close={snapshot.close_price},high={lookback_high})")
        else:
            reasons.append(f"close_below_recent_high(close={snapshot.close_price},high={lookback_high})")

        if volume_ratio >= self.volume_ratio_min:
            reasons.append(
                f"volume_ratio_ok(actual={volume_ratio},min={self.volume_ratio_min},"
                f"target={self.volume_ratio_target})"
            )
        else:
            reasons.append(
                f"volume_ratio_low(actual={volume_ratio},min={self.volume_ratio_min},"
                f"target={self.volume_ratio_target})"
            )

        if close_strength_ratio >= self.close_strength_min:
            reasons.append(
                f"close_strength_ok(actual={close_strength_ratio},min={self.close_strength_min})"
            )
        else:
            reasons.append(
                f"close_strength_low(actual={close_strength_ratio},min={self.close_strength_min})"
            )

        passed = (
            price_condition_passed
            and volume_ratio >= self.volume_ratio_min
            and close_strength_ratio >= self.close_strength_min
        )
        return CloseConfirmationResult(
            passed=passed,
            reasons=tuple(reasons),
            lookback_high=lookback_high,
            average_volume=average_volume,
            volume_ratio=volume_ratio,
            close_strength_ratio=close_strength_ratio,
        )

    @staticmethod
    def _calculate_close_strength_ratio(snapshot: MarketDataSnapshot) -> Decimal:
        if snapshot.high_price <= Decimal("0"):
            return Decimal("0")
        return snapshot.close_price / snapshot.high_price
