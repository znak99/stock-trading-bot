"""Config loading helpers for backtest and experiment execution."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True, frozen=True, kw_only=True)
class BacktestConfigBundle:
    """Resolved configuration bundle for one backtest runtime build."""

    project_root: Path
    base: dict[str, Any]
    mode: dict[str, Any]
    strategy: dict[str, Any]
    risk: dict[str, Any]
    costs: dict[str, Any]
    market: dict[str, Any]


class ConfigManager:
    """Load repository configs and merge override dictionaries safely."""

    def __init__(self, *, project_root: Path) -> None:
        self._project_root = project_root

    @property
    def project_root(self) -> Path:
        """Return the repository root used for config resolution."""

        return self._project_root

    def load_backtest_config_bundle(
        self,
        *,
        overrides: Mapping[str, Any] | None = None,
    ) -> BacktestConfigBundle:
        """Load the active config bundle with optional per-section overrides."""

        override_map = deepcopy(dict(overrides or {}))

        base_config = self.deep_merge(
            self.load_yaml(self._project_root / "configs" / "base.yaml"),
            override_map.get("base", {}),
        )
        mode_profile = str(base_config["profiles"]["mode"])
        strategy_profile = str(base_config["profiles"]["strategy"])
        risk_profile = str(base_config["profiles"]["risk"])
        costs_profile = str(base_config["profiles"]["costs"])
        market_profile = str(base_config["profiles"]["market"])

        mode_config = self.deep_merge(
            self.load_yaml(self._project_root / "configs" / "modes" / f"{mode_profile}.yaml"),
            override_map.get("mode", {}),
        )
        strategy_config = self.deep_merge(
            self.load_yaml(
                self._project_root / "configs" / "strategy" / f"{strategy_profile}.yaml"
            ),
            override_map.get("strategy", {}),
        )
        risk_config = self.deep_merge(
            self.load_yaml(self._project_root / "configs" / "risk" / f"{risk_profile}.yaml"),
            override_map.get("risk", {}),
        )
        costs_config = self.deep_merge(
            self.load_yaml(
                self._project_root / "configs" / "costs" / f"{costs_profile}.yaml"
            ),
            override_map.get("costs", {}),
        )
        market_config = self.deep_merge(
            self.load_yaml(
                self._project_root / "configs" / "market" / f"{market_profile}.yaml"
            ),
            override_map.get("market", {}),
        )

        return BacktestConfigBundle(
            project_root=self._project_root,
            base=base_config,
            mode=mode_config,
            strategy=strategy_config,
            risk=risk_config,
            costs=costs_config,
            market=market_config,
        )

    @staticmethod
    def load_yaml(path: Path) -> dict[str, Any]:
        """Load one YAML config file as a mapping."""

        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        if not isinstance(data, dict):
            raise ValueError(f"Expected a mapping in {path}.")
        return data

    @classmethod
    def build_override_from_path(cls, path: str, value: Any) -> dict[str, Any]:
        """Convert a dotted override path into a nested config mapping."""

        parts = tuple(part for part in path.split(".") if part)
        if len(parts) < 2:
            raise ValueError(
                "Override paths must start with a config section name. "
                f"path={path!r}"
            )

        nested: Any = value
        for part in reversed(parts):
            nested = {part: nested}
        if not isinstance(nested, dict):
            raise ValueError(f"Failed to build override mapping for path={path!r}.")
        return nested

    @classmethod
    def deep_merge(
        cls,
        base: Mapping[str, Any],
        override: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Recursively merge override values into a copied base mapping."""

        merged = deepcopy(dict(base))
        for key, override_value in override.items():
            base_value = merged.get(key)
            if isinstance(base_value, dict) and isinstance(override_value, Mapping):
                merged[key] = cls.deep_merge(base_value, override_value)
            else:
                merged[key] = deepcopy(override_value)
        return merged
