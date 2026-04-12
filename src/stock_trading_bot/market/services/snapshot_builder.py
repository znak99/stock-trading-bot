"""Builders for standardized market data snapshots."""

from __future__ import annotations

from collections.abc import Iterable

from stock_trading_bot.core.models import MarketDataSnapshot
from stock_trading_bot.market.services.indicator_preprocessor import (
    EnrichedHistoricalBar,
    HistoricalOhlcvBar,
)


BarLike = HistoricalOhlcvBar | EnrichedHistoricalBar


class SnapshotBuilder:
    """Create MarketDataSnapshot objects from typed OHLCV bars."""

    def build(
        self,
        bar: BarLike,
        *,
        session_phase: str = "MARKET_CLOSE_PROCESS",
        is_final: bool = True,
    ) -> MarketDataSnapshot:
        """Build a single standardized snapshot."""

        return MarketDataSnapshot(
            snapshot_id=self.build_snapshot_id(bar.instrument_id, bar.timestamp),
            instrument_id=bar.instrument_id,
            timestamp=bar.timestamp,
            open_price=bar.open_price,
            high_price=bar.high_price,
            low_price=bar.low_price,
            close_price=bar.close_price,
            volume=bar.volume,
            trading_value=bar.trading_value,
            change_rate=bar.change_rate,
            is_final=is_final,
            session_phase=session_phase,
        )

    def build_many(
        self,
        bars: Iterable[BarLike],
        *,
        session_phase: str = "MARKET_CLOSE_PROCESS",
        is_final: bool = True,
    ) -> tuple[MarketDataSnapshot, ...]:
        """Build snapshots for an iterable of bars."""

        return tuple(
            self.build(
                bar,
                session_phase=session_phase,
                is_final=is_final,
            )
            for bar in bars
        )

    @staticmethod
    def build_snapshot_id(instrument_id: str, timestamp: object) -> str:
        """Return a deterministic snapshot identifier."""

        return f"{instrument_id}:{timestamp}"
