"""Config-driven parameter experiment runner."""

from __future__ import annotations

import argparse
import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import product
from pathlib import Path
from typing import Any

from stock_trading_bot.app.run_backtest import run_backtest
from stock_trading_bot.infrastructure._serialization import dump_json, to_serializable
from stock_trading_bot.infrastructure.config import ConfigManager
from stock_trading_bot.runtime.result_collector import BacktestSummary


@dataclass(slots=True, frozen=True, kw_only=True)
class ParameterExperimentRunSpec:
    """One generated parameter experiment run definition."""

    run_id: str
    parameter_values: dict[str, Any]
    config_overrides: dict[str, Any]


@dataclass(slots=True, frozen=True, kw_only=True)
class ParameterExperimentRunResult:
    """One completed experiment run with summary and artifact locations."""

    run_id: str
    parameter_values: dict[str, Any]
    config_overrides: dict[str, Any]
    summary: BacktestSummary
    result_directory: Path | None
    log_directory: Path | None


@dataclass(slots=True, frozen=True, kw_only=True)
class ParameterExperimentReport:
    """Comparison report for a parameter experiment session."""

    experiment_name: str
    comparison_metric: str
    metrics: tuple[str, ...]
    baseline_run_id: str | None
    best_run_id: str
    output_directory: Path
    runs: tuple[ParameterExperimentRunResult, ...]


def run_parameter_experiments(
    *,
    experiment_config_path: Path,
    project_root: Path | None = None,
    data_directory: Path | None = None,
    result_directory: Path | None = None,
    log_directory: Path | None = None,
) -> ParameterExperimentReport:
    """Execute repeated backtests from an experiment config and compare outcomes."""

    root = project_root or Path(__file__).resolve().parents[3]
    config_manager = ConfigManager(project_root=root)
    resolved_experiment_config_path = _resolve_experiment_config_path(root, experiment_config_path)
    experiment_config = config_manager.load_yaml(resolved_experiment_config_path)

    experiment_name = str(experiment_config["name"])
    base_overrides = dict(experiment_config.get("base_overrides", {}))
    resolved_bundle = config_manager.load_backtest_config_bundle(overrides=base_overrides)

    comparison_config = dict(experiment_config.get("comparison", {}))
    comparison_metric = str(comparison_config.get("sort_by", "total_pnl"))
    metrics = tuple(
        comparison_config.get(
            "metrics",
            (
                "total_pnl",
                "return_rate",
                "realized_pnl",
                "order_request_count",
                "fill_event_count",
            ),
        )
    )
    if comparison_metric not in metrics:
        metrics = (*metrics, comparison_metric)

    paths_config = dict(experiment_config.get("paths", {}))
    experiment_output_directory = _resolve_experiment_output_directory(
        root=root,
        base_config=resolved_bundle.base,
        experiment_name=experiment_name,
        override_directory=result_directory,
        configured_directory=paths_config.get("output_dir"),
    )
    experiment_result_root = _resolve_experiment_output_directory(
        root=root,
        base_config=resolved_bundle.base,
        experiment_name=experiment_name,
        override_directory=result_directory,
        configured_directory=paths_config.get("result_dir"),
        default_suffix="results/experiments",
    )
    experiment_log_root = _resolve_experiment_output_directory(
        root=root,
        base_config=resolved_bundle.base,
        experiment_name=experiment_name,
        override_directory=log_directory,
        configured_directory=paths_config.get("log_dir"),
        default_suffix="logs/experiments",
    )

    run_specs = _build_run_specs(experiment_config)
    run_results: list[ParameterExperimentRunResult] = []
    for run_spec in run_specs:
        merged_overrides = ConfigManager.deep_merge(base_overrides, run_spec.config_overrides)
        backtest_result = run_backtest(
            project_root=root,
            data_directory=data_directory,
            result_directory=experiment_result_root / run_spec.run_id,
            log_directory=experiment_log_root / run_spec.run_id,
            config_overrides=merged_overrides,
        )
        run_results.append(
            ParameterExperimentRunResult(
                run_id=run_spec.run_id,
                parameter_values=run_spec.parameter_values,
                config_overrides=merged_overrides,
                summary=backtest_result.summary,
                result_directory=_resolve_single_child_directory(
                    experiment_result_root / run_spec.run_id
                ),
                log_directory=_resolve_single_child_directory(
                    experiment_log_root / run_spec.run_id
                ),
            )
        )

    if not run_results:
        raise ValueError("At least one experiment run must be generated.")

    sorted_run_results = tuple(
        sorted(
            run_results,
            key=lambda run_result: _metric_sort_value(run_result.summary, comparison_metric),
            reverse=True,
        )
    )
    baseline_run_id = next(
        (
            run_result.run_id
            for run_result in run_results
            if run_result.run_id == "baseline"
        ),
        None,
    )
    report = ParameterExperimentReport(
        experiment_name=experiment_name,
        comparison_metric=comparison_metric,
        metrics=metrics,
        baseline_run_id=baseline_run_id,
        best_run_id=sorted_run_results[0].run_id,
        output_directory=experiment_output_directory,
        runs=tuple(run_results),
    )
    _persist_experiment_report(report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for config-driven parameter experiments."""

    parser = argparse.ArgumentParser(description="Run parameter experiments for the backtest.")
    parser.add_argument(
        "--experiment-config",
        type=Path,
        required=True,
        help="Experiment YAML path. Relative paths resolve from the repository root.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Repository root containing configs/ and data/.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Historical CSV directory. Defaults to configs/base.yaml paths.data_root.",
    )
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=None,
        help="Root directory for per-run backtest artifacts.",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Root directory for per-run event logs.",
    )
    args = parser.parse_args(argv)

    report = run_parameter_experiments(
        experiment_config_path=args.experiment_config,
        project_root=args.project_root,
        data_directory=args.data_dir,
        result_directory=args.result_dir,
        log_directory=args.log_dir,
    )
    print("Parameter experiments completed.")
    print(f"experiment={report.experiment_name}")
    print(f"runs={len(report.runs)}")
    print(f"comparison_metric={report.comparison_metric}")
    print(f"best_run={report.best_run_id}")
    print(f"output_dir={report.output_directory}")
    for run_result in report.runs:
        print(
            f"run={run_result.run_id} "
            f"total_pnl={run_result.summary.total_pnl} "
            f"return_rate={run_result.summary.return_rate} "
            f"orders={run_result.summary.order_request_count}"
        )
    return 0


def _build_run_specs(
    experiment_config: Mapping[str, Any],
) -> tuple[ParameterExperimentRunSpec, ...]:
    parameters = tuple(experiment_config.get("parameters", ()))
    include_baseline = bool(experiment_config.get("include_baseline", True))

    run_specs: list[ParameterExperimentRunSpec] = []
    if include_baseline:
        run_specs.append(
            ParameterExperimentRunSpec(
                run_id="baseline",
                parameter_values={},
                config_overrides={},
            )
        )

    if not parameters:
        return tuple(run_specs)

    parameter_names = tuple(str(parameter_config["path"]) for parameter_config in parameters)
    parameter_values_list = tuple(
        tuple(parameter_config["values"])
        for parameter_config in parameters
    )
    if any(not values for values in parameter_values_list):
        raise ValueError("Experiment parameter values must not be empty.")

    for index, combination in enumerate(product(*parameter_values_list), start=1):
        parameter_values = dict(zip(parameter_names, combination, strict=True))
        config_overrides: dict[str, Any] = {}
        for path, value in parameter_values.items():
            config_overrides = ConfigManager.deep_merge(
                config_overrides,
                ConfigManager.build_override_from_path(path, value),
            )
        run_specs.append(
            ParameterExperimentRunSpec(
                run_id=f"run_{index:03d}",
                parameter_values=parameter_values,
                config_overrides=config_overrides,
            )
        )

    return tuple(run_specs)


def _persist_experiment_report(report: ParameterExperimentReport) -> None:
    report.output_directory.mkdir(parents=True, exist_ok=True)
    comparison_json_path = report.output_directory / "comparison.json"
    comparison_csv_path = report.output_directory / "comparison.csv"

    baseline_run = next(
        (run for run in report.runs if run.run_id == report.baseline_run_id),
        None,
    )
    baseline_metrics = (
        {
            metric: getattr(baseline_run.summary, metric)
            for metric in report.metrics
        }
        if baseline_run is not None
        else {}
    )

    comparison_rows = []
    for run_result in report.runs:
        metric_values = {
            metric: getattr(run_result.summary, metric)
            for metric in report.metrics
        }
        comparison_rows.append(
            {
                "run_id": run_result.run_id,
                "parameter_values": run_result.parameter_values,
                "config_overrides": run_result.config_overrides,
                "metrics": metric_values,
                "deltas_vs_baseline": {
                    metric: _delta_value(metric_values[metric], baseline_metrics.get(metric))
                    for metric in report.metrics
                    if metric in baseline_metrics
                },
                "result_directory": run_result.result_directory,
                "log_directory": run_result.log_directory,
            }
        )

    dump_json(
        comparison_json_path,
        {
            "experiment_name": report.experiment_name,
            "comparison_metric": report.comparison_metric,
            "baseline_run_id": report.baseline_run_id,
            "best_run_id": report.best_run_id,
            "runs": comparison_rows,
        },
    )

    parameter_columns = tuple(
        sorted(
            {
                parameter_name
                for run_result in report.runs
                for parameter_name in run_result.parameter_values
            }
        )
    )
    with comparison_csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "run_id",
            *parameter_columns,
            *report.metrics,
            *(f"delta_{metric}" for metric in report.metrics if baseline_run is not None),
            "result_directory",
            "log_directory",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in comparison_rows:
            writer.writerow(
                {
                    "run_id": row["run_id"],
                    **{
                        parameter_column: row["parameter_values"].get(parameter_column, "")
                        for parameter_column in parameter_columns
                    },
                    **{
                        metric: to_serializable(row["metrics"][metric])
                        for metric in report.metrics
                    },
                    **{
                        f"delta_{metric}": to_serializable(
                            row["deltas_vs_baseline"].get(metric)
                        )
                        for metric in report.metrics
                        if baseline_run is not None
                    },
                    "result_directory": to_serializable(row["result_directory"]),
                    "log_directory": to_serializable(row["log_directory"]),
                }
            )


def _resolve_experiment_config_path(root: Path, experiment_config_path: Path) -> Path:
    if experiment_config_path.is_absolute():
        return experiment_config_path
    if experiment_config_path.exists():
        return experiment_config_path
    return root / experiment_config_path


def _resolve_experiment_output_directory(
    *,
    root: Path,
    base_config: Mapping[str, Any],
    experiment_name: str,
    override_directory: Path | None,
    configured_directory: str | None,
    default_suffix: str = "results/experiments",
) -> Path:
    if override_directory is not None:
        return override_directory / experiment_name
    if configured_directory is not None:
        return root / configured_directory / experiment_name

    base_path = (
        base_config["paths"]["result_dir"]
        if default_suffix.startswith("results")
        else base_config["paths"]["log_dir"]
    )
    _, suffix = default_suffix.split("/", maxsplit=1)
    return root / base_path / suffix / experiment_name


def _resolve_single_child_directory(path: Path) -> Path | None:
    if not path.exists():
        return None
    child_directories = sorted(child for child in path.iterdir() if child.is_dir())
    if not child_directories:
        return None
    if len(child_directories) != 1:
        raise ValueError(
            f"Expected one artifact directory in {path}, "
            f"found {len(child_directories)}."
        )
    return child_directories[0]


def _metric_sort_value(summary: BacktestSummary, metric: str) -> Decimal | int:
    metric_value = getattr(summary, metric)
    if not isinstance(metric_value, Decimal | int):
        raise ValueError(f"Unsupported comparison metric type for {metric!r}.")
    return metric_value


def _delta_value(current_value: Any, baseline_value: Any) -> Any:
    if baseline_value is None:
        return None
    if isinstance(current_value, Decimal | int) and isinstance(baseline_value, Decimal | int):
        return current_value - baseline_value
    return None


if __name__ == "__main__":
    raise SystemExit(main())
