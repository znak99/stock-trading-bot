"""Config manager tests."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from stock_trading_bot.infrastructure import ConfigManager


def test_config_manager_loads_bundle_with_section_overrides() -> None:
    project_root = Path(__file__).resolve().parents[3]
    config_manager = ConfigManager(project_root=project_root)

    bundle = config_manager.load_backtest_config_bundle(
        overrides={
            "strategy": {
                "entry": {
                    "volume_ratio_min": 3.0,
                }
            },
            "mode": {
                "backtest": {
                    "initial_cash_balance": 1234567,
                }
            },
        }
    )

    assert bundle.strategy["entry"]["volume_ratio_min"] == 3.0
    assert bundle.mode["backtest"]["initial_cash_balance"] == 1234567
    assert Decimal(str(bundle.costs["buy_commission_rate"])) == Decimal("0.00025")


def test_build_override_from_path_creates_nested_section_mapping() -> None:
    override = ConfigManager.build_override_from_path(
        "strategy.entry.volume_ratio_min",
        2.5,
    )

    assert override == {
        "strategy": {
            "entry": {
                "volume_ratio_min": 2.5,
            }
        }
    }
