"""In-memory position book."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from stock_trading_bot.core.models import Position


class PositionBook:
    """Store and query current position state keyed by instrument."""

    def __init__(self, positions: Iterable[Position] | None = None) -> None:
        self._positions: dict[str, Position] = {}
        for position in positions or ():
            self.upsert(position)

    def get(self, instrument_id: str) -> Position | None:
        """Return the current position for an instrument, if any."""

        return self._positions.get(instrument_id)

    def upsert(self, position: Position) -> None:
        """Insert or replace a position."""

        self._positions[position.instrument_id] = position

    def all_positions(self) -> tuple[Position, ...]:
        """Return all tracked positions."""

        return tuple(self._positions.values())

    def open_positions(self) -> tuple[Position, ...]:
        """Return only active open positions."""

        return tuple(
            position
            for position in self._positions.values()
            if position.position_status == "open" and position.quantity > Decimal("0")
        )

    def active_position_count(self) -> int:
        """Return the number of active open positions."""

        return len(self.open_positions())

    def total_market_value(self) -> Decimal:
        """Return the aggregated market value of open positions."""

        return sum(
            (position.current_price * position.quantity for position in self.open_positions()),
            start=Decimal("0"),
        )

    def position_refs(self, instrument_id: str | None = None) -> tuple[str, ...]:
        """Return position identifiers for one instrument or all tracked positions."""

        if instrument_id is None:
            return tuple(position.position_id for position in self._positions.values())

        position = self.get(instrument_id)
        if position is None:
            return ()
        return (position.position_id,)

