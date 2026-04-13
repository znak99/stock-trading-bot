"""Integration tests for AI ranking in the backtest runtime."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from stock_trading_bot.app.run_backtest import run_backtest


def test_backtest_runtime_uses_ai_scoring_and_sorts_candidates(tmp_path: Path) -> None:
    _write_breakout_fixture(
        tmp_path / "A001.csv",
        close_offset=Decimal("0"),
        breakout_close=Decimal("120.5"),
        breakout_high=Decimal("121"),
        breakout_volume=3_200_000,
    )
    _write_breakout_fixture(
        tmp_path / "A002.csv",
        close_offset=Decimal("2"),
        breakout_close=Decimal("121.2"),
        breakout_high=Decimal("122"),
        breakout_volume=1_700_000,
    )

    result = run_backtest(data_directory=tmp_path)

    assert len(result.scores) == 2
    assert [score.rank for score in result.scores] == [1, 2]
    assert [score.instrument_id for score in result.scores] == ["A001", "A002"]
    assert all(score.model_name == "advanced_ranking_model" for score in result.scores)
    assert result.scores[0].score_value > result.scores[1].score_value
    assert "price_momentum=" in result.scores[0].score_reason_summary
    assert "gap_penalty=" in result.scores[0].score_reason_summary


def _write_breakout_fixture(
    path: Path,
    *,
    close_offset: Decimal,
    breakout_close: Decimal,
    breakout_high: Decimal,
    breakout_volume: int,
) -> None:
    fieldnames = ("date", "open", "high", "low", "close", "volume")
    rows: list[dict[str, str]] = []
    start_date = date(2024, 1, 1)

    for offset in range(20):
        base_price = Decimal("100") + Decimal(offset) + close_offset
        rows.append(
            {
                "date": (start_date + timedelta(days=offset)).isoformat(),
                "open": str(base_price - Decimal("1")),
                "high": str(base_price),
                "low": str(base_price - Decimal("2")),
                "close": str(base_price - Decimal("0.5")),
                "volume": "1000000",
            }
        )

    rows.extend(
        (
            {
                "date": date(2024, 1, 21).isoformat(),
                "open": str(breakout_close - Decimal("1")),
                "high": str(breakout_high),
                "low": str(breakout_close - Decimal("2")),
                "close": str(breakout_close),
                "volume": str(breakout_volume),
            },
            {
                "date": date(2024, 1, 22).isoformat(),
                "open": str(breakout_close + Decimal("1")),
                "high": str(breakout_close + Decimal("2")),
                "low": str(breakout_close - Decimal("1")),
                "close": str(breakout_close + Decimal("0.3")),
                "volume": "1200000",
            },
        )
    )

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
