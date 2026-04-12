"""Application entrypoints."""

from pathlib import Path


def build_backtest_runtime(*, project_root: Path | None = None, data_directory: Path | None = None):
    """Proxy to the backtest runtime builder without eager module import."""

    from .run_backtest import build_backtest_runtime as _build_backtest_runtime

    return _build_backtest_runtime(
        project_root=project_root,
        data_directory=data_directory,
    )


def run_backtest(*, project_root: Path | None = None, data_directory: Path | None = None):
    """Proxy to the backtest runner without eager module import."""

    from .run_backtest import run_backtest as _run_backtest

    return _run_backtest(
        project_root=project_root,
        data_directory=data_directory,
    )


__all__ = ["build_backtest_runtime", "run_backtest"]
