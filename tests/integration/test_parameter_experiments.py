"""Parameter experiment integration tests."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import yaml

from stock_trading_bot.app.run_parameter_experiments import (
    main,
    run_parameter_experiments,
)


def test_parameter_experiments_compare_different_parameter_outcomes(tmp_path: Path) -> None:
    data_directory = tmp_path / "market"
    data_directory.mkdir(parents=True, exist_ok=True)
    _write_e2e_fixture(data_directory / "005930.csv")

    experiment_config_path = tmp_path / "experiment.yaml"
    experiment_config_path.write_text(
        yaml.safe_dump(
            {
                "name": "volume_ratio_experiment",
                "include_baseline": True,
                "comparison": {
                    "sort_by": "total_pnl",
                    "metrics": [
                        "total_pnl",
                        "return_rate",
                        "order_request_count",
                        "fill_event_count",
                    ],
                },
                "parameters": [
                    {
                        "path": "strategy.entry.close_strength_min",
                        "values": [0.995],
                    }
                ],
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    report = run_parameter_experiments(
        experiment_config_path=experiment_config_path,
        data_directory=data_directory,
        result_directory=tmp_path / "experiment_results",
        log_directory=tmp_path / "experiment_logs",
    )

    comparison_json = _read_json(report.output_directory / "comparison.json")
    comparison_csv = (report.output_directory / "comparison.csv").read_text(encoding="utf-8")
    baseline_run = next(run for run in report.runs if run.run_id == "baseline")
    experimental_run = next(run for run in report.runs if run.run_id != "baseline")

    assert len(report.runs) == 2
    assert report.best_run_id == "baseline"
    assert baseline_run.summary.total_pnl > experimental_run.summary.total_pnl
    assert baseline_run.summary.order_request_count > experimental_run.summary.order_request_count
    assert experimental_run.summary.total_pnl == Decimal("0")
    assert comparison_json["best_run_id"] == "baseline"
    assert len(comparison_json["runs"]) == 2
    assert "delta_total_pnl" in comparison_csv


def test_parameter_experiment_main_prints_summary(tmp_path: Path, capsys) -> None:
    data_directory = tmp_path / "market"
    data_directory.mkdir(parents=True, exist_ok=True)
    _write_e2e_fixture(data_directory / "005930.csv")

    experiment_config_path = tmp_path / "experiment.yaml"
    experiment_config_path.write_text(
        yaml.safe_dump(
            {
                "name": "single_parameter_experiment",
                "include_baseline": True,
                "parameters": [
                    {
                        "path": "strategy.entry.close_strength_min",
                        "values": [0.995],
                    }
                ],
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--experiment-config",
            str(experiment_config_path),
            "--data-dir",
            str(data_directory),
            "--result-dir",
            str(tmp_path / "cli_results"),
            "--log-dir",
            str(tmp_path / "cli_logs"),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Parameter experiments completed." in output
    assert "best_run=baseline" in output
    assert "runs=2" in output


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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
