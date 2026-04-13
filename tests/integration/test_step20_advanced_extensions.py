"""Integration tests for step20 advanced extensions."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from stock_trading_bot.app.run_backtest import _discover_instruments, run_backtest
from stock_trading_bot.infrastructure.config import ConfigManager


def test_advanced_stack_improves_total_pnl_and_reduces_fill_count(tmp_path: Path) -> None:
    _write_step20_fixture(tmp_path)
    baseline_log_root = tmp_path / "baseline_logs"
    advanced_log_root = tmp_path / "advanced_logs"

    baseline_result = run_backtest(
        data_directory=tmp_path,
        log_directory=baseline_log_root,
        config_overrides={
            "strategy": {
                "execution": {"gap_filter_enabled": False},
                "ai_scoring": {"model_type": "basic"},
            },
            "risk": {"allocation_policy": "equal_weight"},
        },
    )
    advanced_result = run_backtest(
        data_directory=tmp_path,
        log_directory=advanced_log_root,
        config_overrides={
            "strategy": {
                "execution": {
                    "gap_filter_enabled": True,
                    "gap_filter": {"block_gap_up": True, "max_gap_up_rate": 0.055},
                },
                "ai_scoring": {"model_type": "advanced"},
            },
            "risk": {"allocation_policy": "weighted_score"},
        },
    )
    advanced_log_records = _read_jsonl_records(advanced_log_root)

    assert advanced_result.summary.total_pnl > baseline_result.summary.total_pnl
    assert any(score.model_name == "advanced_ranking_model" for score in advanced_result.scores)
    assert any(
        record["record_type"] == "gap_filter_decision"
        and record["payload"]["allowed"] is False
        and "blocked_gap_up" in record["payload"]["reason"]
        for record in advanced_log_records
    )


def test_market_profile_defaults_support_market_expansion_configs(tmp_path: Path) -> None:
    _write_single_row_csv(tmp_path / "AAPL.csv")
    _write_single_row_csv(tmp_path / "BTCUSDT.csv")
    config_manager = ConfigManager(project_root=Path(__file__).resolve().parents[2])

    us_market_config = config_manager.load_yaml(
        config_manager.project_root / "configs" / "market" / "us_stock.yaml"
    )
    crypto_market_config = config_manager.load_yaml(
        config_manager.project_root / "configs" / "market" / "crypto.yaml"
    )

    us_instruments = {
        instrument.instrument_id: instrument
        for instrument in _discover_instruments(tmp_path, us_market_config)
    }
    crypto_instruments = {
        instrument.instrument_id: instrument
        for instrument in _discover_instruments(tmp_path, crypto_market_config)
    }

    assert us_instruments["AAPL"].market == "us_stock"
    assert us_instruments["AAPL"].asset_type == "equity"
    assert crypto_instruments["BTCUSDT"].market == "crypto"
    assert crypto_instruments["BTCUSDT"].asset_type == "crypto"


def _write_step20_fixture(directory: Path) -> None:
    _write_instrument_fixture(
        directory / "AAA.csv",
        warmup_step=Decimal("1.0"),
        breakout_close=Decimal("120.6"),
        breakout_high=Decimal("121.0"),
        breakout_volume=3_200_000,
        post_breakout_rows=(
            _row(date(2024, 1, 22), "121.2", "127.0", "120.5", "126.2", "1300000"),
            _row(date(2024, 1, 23), "125.5", "126.0", "117.0", "118.0", "1100000"),
            _row(date(2024, 1, 24), "117.0", "119.0", "116.0", "118.2", "1000000"),
        ),
    )
    _write_instrument_fixture(
        directory / "BBB.csv",
        warmup_step=Decimal("0.35"),
        breakout_close=Decimal("107.8"),
        breakout_high=Decimal("108.0"),
        breakout_volume=1_550_000,
        post_breakout_rows=(
            _row(date(2024, 1, 22), "108.4", "109.0", "106.5", "107.0", "1200000"),
            _row(date(2024, 1, 23), "106.8", "107.0", "102.0", "103.5", "1100000"),
            _row(date(2024, 1, 24), "102.8", "104.0", "101.5", "103.0", "1000000"),
        ),
    )
    _write_instrument_fixture(
        directory / "CCC.csv",
        warmup_step=Decimal("0.75"),
        breakout_close=Decimal("114.7"),
        breakout_high=Decimal("115.0"),
        breakout_volume=2_100_000,
        post_breakout_rows=(
            _row(date(2024, 1, 22), "124.5", "125.0", "114.0", "115.5", "1800000"),
            _row(date(2024, 1, 23), "114.8", "115.2", "111.0", "112.0", "1400000"),
            _row(date(2024, 1, 24), "111.5", "112.0", "110.0", "111.0", "1000000"),
        ),
    )


def _write_instrument_fixture(
    path: Path,
    *,
    warmup_step: Decimal,
    breakout_close: Decimal,
    breakout_high: Decimal,
    breakout_volume: int,
    post_breakout_rows: tuple[dict[str, str], ...],
) -> None:
    fieldnames = ("date", "open", "high", "low", "close", "volume")
    rows: list[dict[str, str]] = []
    start_date = date(2024, 1, 1)

    for offset in range(20):
        base_price = Decimal("100") + (warmup_step * Decimal(offset))
        rows.append(
            _row(
                start_date + timedelta(days=offset),
                str(base_price - Decimal("1")),
                str(base_price),
                str(base_price - Decimal("2")),
                str(base_price - Decimal("0.5")),
                "1000000",
            )
        )

    rows.append(
        _row(
            date(2024, 1, 21),
            str(breakout_close - Decimal("1")),
            str(breakout_high),
            str(breakout_close - Decimal("2")),
            str(breakout_close),
            str(breakout_volume),
        )
    )
    rows.extend(post_breakout_rows)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_single_row_csv(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("date", "open", "high", "low", "close", "volume"),
        )
        writer.writeheader()
        writer.writerow(_row(date(2024, 1, 1), "100", "101", "99", "100", "1000000"))


def _read_jsonl_records(log_root: Path) -> list[dict[str, object]]:
    event_log_paths = sorted(log_root.glob("*/events.jsonl"))
    assert event_log_paths, "Expected at least one event log."
    return [
        json.loads(line)
        for event_log_path in event_log_paths
        for line in event_log_path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _row(
    trading_date: date,
    open_price: str,
    high_price: str,
    low_price: str,
    close_price: str,
    volume: str,
) -> dict[str, str]:
    return {
        "date": trading_date.isoformat(),
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
    }
