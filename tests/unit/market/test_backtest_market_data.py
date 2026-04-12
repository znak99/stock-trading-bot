"""Tests for the backtest market data feed and preprocessing."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from stock_trading_bot.adapters import HistoricalMarketDataFeed
from stock_trading_bot.core.models import Instrument
from stock_trading_bot.market import IndicatorPreprocessor, SnapshotBuilder


FIXTURE_DIRECTORY = Path(__file__).resolve().parents[2] / "fixtures" / "market"


def _build_instrument() -> Instrument:
    return Instrument(
        instrument_id="instr-005930",
        symbol="005930",
        name="Samsung Electronics",
        market="KOSPI",
        asset_type="equity",
        sector="IT",
        is_etf=False,
        is_active=True,
    )


def test_historical_market_data_feed_loads_csv_and_builds_snapshots() -> None:
    feed = HistoricalMarketDataFeed(data_directory=FIXTURE_DIRECTORY)
    instrument = _build_instrument()

    bars = feed.load_ohlcv(instrument)
    snapshots = tuple(feed.iter_snapshots(instrument))

    assert len(bars) == 20
    assert bars[0].timestamp == datetime(2026, 1, 1, 0, 0)
    assert bars[0].open_price == Decimal("99")
    assert bars[1].change_rate == Decimal("0.01")
    assert bars[-1].trading_value == Decimal("119000")

    assert len(snapshots) == 20
    assert snapshots[-1].snapshot_id == "instr-005930:2026-01-20 00:00:00"
    assert snapshots[-1].close_price == Decimal("119")
    assert snapshots[-1].volume == 1000
    assert snapshots[-1].trading_value == Decimal("119000")
    assert snapshots[-1].is_final is True
    assert snapshots[-1].session_phase == "MARKET_CLOSE_PROCESS"


def test_indicator_preprocessor_calculates_moving_averages_and_rsi() -> None:
    feed = HistoricalMarketDataFeed(data_directory=FIXTURE_DIRECTORY)
    instrument = _build_instrument()

    enriched_bars = feed.load_enriched_bars(instrument)
    indicator_series = feed.get_indicator_series(instrument)

    assert enriched_bars[3].indicators["sma_5"] is None
    assert enriched_bars[4].indicators["sma_5"] == Decimal("102")
    assert enriched_bars[-1].indicators["sma_5"] == Decimal("117")
    assert enriched_bars[-1].indicators["sma_20"] == Decimal("109.5")
    assert enriched_bars[13].indicators["rsi_14"] is None
    assert enriched_bars[14].indicators["rsi_14"] == Decimal("100")
    assert all(
        value is None or Decimal("0") <= value <= Decimal("100")
        for value in indicator_series["rsi_14"]
    )


def test_snapshot_builder_supports_custom_session_phase_for_preprocessed_bar() -> None:
    feed = HistoricalMarketDataFeed(data_directory=FIXTURE_DIRECTORY)
    instrument = _build_instrument()
    builder = SnapshotBuilder()

    snapshot = builder.build(
        feed.load_enriched_bars(instrument)[-1],
        session_phase="INTRADAY_MONITOR",
        is_final=False,
    )

    assert snapshot.snapshot_id == "instr-005930:2026-01-20 00:00:00"
    assert snapshot.session_phase == "INTRADAY_MONITOR"
    assert snapshot.is_final is False


def test_indicator_preprocessor_returns_expected_indicator_names() -> None:
    preprocessor = IndicatorPreprocessor(moving_average_windows=(3, 5), rsi_period=7)

    assert preprocessor.indicator_names == ("sma_3", "sma_5", "rsi_7")
