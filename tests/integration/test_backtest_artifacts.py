"""Backtest artifact persistence integration tests."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from stock_trading_bot.app.run_backtest import run_backtest


def test_run_backtest_persists_replayable_logs_and_trade_artifacts(tmp_path: Path) -> None:
    fixture_directory = tmp_path / "market"
    fixture_directory.mkdir(parents=True, exist_ok=True)
    _write_e2e_fixture(fixture_directory / "005930.csv")

    result_a = run_backtest(
        data_directory=fixture_directory,
        result_directory=tmp_path / "results_a",
        log_directory=tmp_path / "logs_a",
    )
    result_b = run_backtest(
        data_directory=fixture_directory,
        result_directory=tmp_path / "results_b",
        log_directory=tmp_path / "logs_b",
    )

    saved_result_directory_a = _get_single_child_directory(tmp_path / "results_a")
    saved_result_directory_b = _get_single_child_directory(tmp_path / "results_b")
    saved_log_directory_a = _get_single_child_directory(tmp_path / "logs_a")
    saved_log_directory_b = _get_single_child_directory(tmp_path / "logs_b")

    summary_a = _read_json(saved_result_directory_a / "summary.json")
    summary_b = _read_json(saved_result_directory_b / "summary.json")
    trade_records_a = _normalize_random_fields(
        _read_json(saved_result_directory_a / "trade_records.json")
    )
    trade_records_b = _normalize_random_fields(
        _read_json(saved_result_directory_b / "trade_records.json")
    )
    event_records_a = _normalize_random_fields(_read_jsonl(saved_log_directory_a / "events.jsonl"))
    event_records_b = _normalize_random_fields(_read_jsonl(saved_log_directory_b / "events.jsonl"))

    assert (saved_result_directory_a / "runtime_result.json").exists()
    assert (saved_result_directory_a / "manifest.json").exists()
    assert summary_a == summary_b
    assert trade_records_a == trade_records_b
    assert event_records_a == event_records_b
    assert len(_read_json(saved_result_directory_a / "trade_records.json")) == 3
    assert summary_a["final_equity"] == str(result_a.summary.final_equity)
    assert summary_a["total_pnl"] == str(result_a.summary.total_pnl)
    assert {
        "session_phase",
        "filter_evaluation",
        "candidate_selection",
        "signal",
        "score_result",
        "order_request",
        "order_state_change",
        "fill_event",
        "position_snapshot",
        "pnl_snapshot",
        "backtest_summary",
        "final_account_state",
        "final_positions",
    }.issubset({record["record_type"] for record in event_records_a})
    assert summary_b["final_equity"] == str(result_b.summary.final_equity)


def _get_single_child_directory(path: Path) -> Path:
    children = [child for child in path.iterdir() if child.is_dir()]
    assert len(children) == 1
    return children[0]


def _normalize_random_fields(payload: object) -> object:
    if isinstance(payload, list):
        return [_normalize_random_fields(item) for item in payload]
    if isinstance(payload, dict):
        return {
            key: _normalize_random_fields(value)
            for key, value in payload.items()
            if key not in {"order_event_id", "broker_order_id", "event_log_path"}
        }
    return payload


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_e2e_fixture(path: Path) -> None:
    fieldnames = ("date", "open", "high", "low", "close", "volume")
    rows: list[dict[str, str]] = []
    start_date = date(2024, 1, 1)

    for offset in range(20):
        base_price = Decimal("100") + Decimal(offset)
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
                "open": "119",
                "high": "121",
                "low": "118",
                "close": "120",
                "volume": "2500000",
            },
            {
                "date": date(2024, 1, 22).isoformat(),
                "open": "121",
                "high": "127",
                "low": "120",
                "close": "126",
                "volume": "1200000",
            },
            {
                "date": date(2024, 1, 23).isoformat(),
                "open": "125",
                "high": "126",
                "low": "117",
                "close": "118",
                "volume": "1100000",
            },
            {
                "date": date(2024, 1, 24).isoformat(),
                "open": "123",
                "high": "124",
                "low": "121",
                "close": "122",
                "volume": "1050000",
            },
        )
    )

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
