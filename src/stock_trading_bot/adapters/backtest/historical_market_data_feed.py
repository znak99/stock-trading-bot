"""Historical OHLCV market data feed for backtests."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from stock_trading_bot.core.models import Instrument, MarketDataSnapshot
from stock_trading_bot.market.services import (
    EnrichedHistoricalBar,
    HistoricalOhlcvBar,
    IndicatorPreprocessor,
    SnapshotBuilder,
)


class HistoricalMarketDataFeed:
    """Load CSV OHLCV files and expose snapshots plus precomputed indicators."""

    def __init__(
        self,
        *,
        data_directory: str | Path,
        snapshot_builder: SnapshotBuilder | None = None,
        indicator_preprocessor: IndicatorPreprocessor | None = None,
        default_session_phase: str = "MARKET_CLOSE_PROCESS",
    ) -> None:
        self._data_directory = Path(data_directory)
        self._snapshot_builder = snapshot_builder or SnapshotBuilder()
        self._indicator_preprocessor = indicator_preprocessor or IndicatorPreprocessor()
        self._default_session_phase = default_session_phase
        self._ohlcv_cache: dict[str, tuple[HistoricalOhlcvBar, ...]] = {}
        self._enriched_cache: dict[str, tuple[EnrichedHistoricalBar, ...]] = {}

    def load_ohlcv(self, instrument: Instrument) -> tuple[HistoricalOhlcvBar, ...]:
        """Load and normalize OHLCV rows for the provided instrument."""

        if instrument.instrument_id in self._ohlcv_cache:
            return self._ohlcv_cache[instrument.instrument_id]

        csv_path = self._resolve_csv_path(instrument)
        rows: list[dict[str, str]] = []
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rows.append({key: value for key, value in row.items() if key is not None and value is not None})

        bars = self._rows_to_bars(rows, instrument.instrument_id)
        self._ohlcv_cache[instrument.instrument_id] = bars
        return bars

    def load_enriched_bars(self, instrument: Instrument) -> tuple[EnrichedHistoricalBar, ...]:
        """Load OHLCV rows and attach indicator values."""

        if instrument.instrument_id in self._enriched_cache:
            return self._enriched_cache[instrument.instrument_id]

        enriched_bars = self._indicator_preprocessor.preprocess(self.load_ohlcv(instrument))
        self._enriched_cache[instrument.instrument_id] = enriched_bars
        return enriched_bars

    def build_snapshots(
        self,
        instrument: Instrument,
        *,
        session_phase: str | None = None,
        is_final: bool = True,
    ) -> tuple[MarketDataSnapshot, ...]:
        """Return snapshots built from the instrument's historical bars."""

        return self._snapshot_builder.build_many(
            self.load_enriched_bars(instrument),
            session_phase=session_phase or self._default_session_phase,
            is_final=is_final,
        )

    def iter_snapshots(
        self,
        instrument: Instrument,
        *,
        session_phase: str | None = None,
        is_final: bool = True,
    ) -> Iterator[MarketDataSnapshot]:
        """Iterate over standardized snapshots in chronological order."""

        yield from self.build_snapshots(
            instrument,
            session_phase=session_phase,
            is_final=is_final,
        )

    def get_indicator_series(
        self,
        instrument: Instrument,
    ) -> dict[str, tuple[Decimal | None, ...]]:
        """Return indicator values keyed by indicator name."""

        enriched_bars = self.load_enriched_bars(instrument)
        if not enriched_bars:
            return {}

        indicator_names = tuple(enriched_bars[0].indicators.keys())
        return {
            indicator_name: tuple(bar.indicators[indicator_name] for bar in enriched_bars)
            for indicator_name in indicator_names
        }

    def _resolve_csv_path(self, instrument: Instrument) -> Path:
        candidates = (
            self._data_directory / f"{instrument.symbol}.csv",
            self._data_directory / f"{instrument.instrument_id}.csv",
        )
        for path in candidates:
            if path.exists():
                return path

        raise FileNotFoundError(
            f"Historical OHLCV CSV not found for instrument_id={instrument.instrument_id!r}, "
            f"symbol={instrument.symbol!r} in {self._data_directory}."
        )

    @staticmethod
    def _rows_to_bars(
        rows: list[dict[str, str]],
        instrument_id: str,
    ) -> tuple[HistoricalOhlcvBar, ...]:
        normalized_rows = sorted(rows, key=lambda row: HistoricalMarketDataFeed._parse_timestamp(row))

        bars: list[HistoricalOhlcvBar] = []
        previous_close: Decimal | None = None
        for row in normalized_rows:
            timestamp = HistoricalMarketDataFeed._parse_timestamp(row)
            close_price = HistoricalMarketDataFeed._parse_decimal(row, "close", "close_price")
            volume = HistoricalMarketDataFeed._parse_int(row, "volume")
            trading_value = HistoricalMarketDataFeed._parse_optional_decimal(
                row,
                "trading_value",
            ) or (close_price * Decimal(volume))

            provided_change_rate = HistoricalMarketDataFeed._parse_optional_decimal(
                row,
                "change_rate",
            )
            if provided_change_rate is not None:
                change_rate = provided_change_rate
            elif previous_close in {None, Decimal("0")}:
                change_rate = Decimal("0")
            else:
                change_rate = (close_price - previous_close) / previous_close

            bars.append(
                HistoricalOhlcvBar(
                    instrument_id=instrument_id,
                    timestamp=timestamp,
                    open_price=HistoricalMarketDataFeed._parse_decimal(row, "open", "open_price"),
                    high_price=HistoricalMarketDataFeed._parse_decimal(row, "high", "high_price"),
                    low_price=HistoricalMarketDataFeed._parse_decimal(row, "low", "low_price"),
                    close_price=close_price,
                    volume=volume,
                    trading_value=trading_value,
                    change_rate=change_rate,
                )
            )
            previous_close = close_price

        return tuple(bars)

    @staticmethod
    def _parse_timestamp(row: dict[str, str]) -> datetime:
        value = row.get("timestamp") or row.get("date")
        if not value:
            raise ValueError("CSV rows must contain a 'timestamp' or 'date' column.")
        return datetime.fromisoformat(value)

    @staticmethod
    def _parse_decimal(row: dict[str, str], *field_names: str) -> Decimal:
        value = HistoricalMarketDataFeed._find_value(row, *field_names)
        return Decimal(value)

    @staticmethod
    def _parse_optional_decimal(row: dict[str, str], *field_names: str) -> Decimal | None:
        value = HistoricalMarketDataFeed._find_value(row, *field_names, required=False)
        return None if value is None else Decimal(value)

    @staticmethod
    def _parse_int(row: dict[str, str], *field_names: str) -> int:
        value = HistoricalMarketDataFeed._find_value(row, *field_names)
        return int(value)

    @staticmethod
    def _find_value(
        row: dict[str, str],
        *field_names: str,
        required: bool = True,
    ) -> str | None:
        for field_name in field_names:
            if field_name in row and row[field_name] != "":
                return row[field_name]
        if required:
            joined_names = ", ".join(field_names)
            raise ValueError(f"CSV row is missing one of the required columns: {joined_names}.")
        return None
