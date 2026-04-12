"""Application entrypoints."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any


def build_backtest_runtime(
    *,
    project_root: Path | None = None,
    data_directory: Path | None = None,
    result_directory: Path | None = None,
    log_directory: Path | None = None,
    config_overrides: Mapping[str, Any] | None = None,
):
    """Proxy to the backtest runtime builder without eager module import."""

    from .run_backtest import build_backtest_runtime as _build_backtest_runtime

    return _build_backtest_runtime(
        project_root=project_root,
        data_directory=data_directory,
        result_directory=result_directory,
        log_directory=log_directory,
        config_overrides=config_overrides,
    )


def run_backtest(
    *,
    project_root: Path | None = None,
    data_directory: Path | None = None,
    result_directory: Path | None = None,
    log_directory: Path | None = None,
    config_overrides: Mapping[str, Any] | None = None,
):
    """Proxy to the backtest runner without eager module import."""

    from .run_backtest import run_backtest as _run_backtest

    return _run_backtest(
        project_root=project_root,
        data_directory=data_directory,
        result_directory=result_directory,
        log_directory=log_directory,
        config_overrides=config_overrides,
    )


def run_parameter_experiments(
    *,
    experiment_config_path: Path,
    project_root: Path | None = None,
    data_directory: Path | None = None,
    result_directory: Path | None = None,
    log_directory: Path | None = None,
):
    """Proxy to the experiment runner without eager module import."""

    from .run_parameter_experiments import run_parameter_experiments as _runner

    return _runner(
        experiment_config_path=experiment_config_path,
        project_root=project_root,
        data_directory=data_directory,
        result_directory=result_directory,
        log_directory=log_directory,
    )


__all__ = ["build_backtest_runtime", "run_backtest", "run_parameter_experiments"]
