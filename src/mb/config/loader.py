from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from mb.config.models import BaselinesConfig, MarketConfig, StrategyConfig


class ConfigError(Exception):
    pass


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    return data


def _validate[T: BaseModel](model: type[T], data: dict[str, Any], where: str) -> T:
    try:
        return model.model_validate(data)
    except ValidationError as e:
        lines = [f"  {'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}" for err in e.errors()]
        raise ConfigError(f"invalid config {where}:\n" + "\n".join(lines)) from None


@dataclass(frozen=True)
class Resolved:
    strategy: StrategyConfig
    params: BaseModel
    market: MarketConfig
    baselines: BaselinesConfig
    strategy_path: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": {**self.strategy.model_dump(mode="json"), "params": self.params.model_dump(mode="json")},
            "market": self.market.model_dump(mode="json"),
            "baselines": self.baselines.model_dump(mode="json"),
        }

    def yaml_text(self) -> str:
        return yaml.safe_dump(self.as_dict(), sort_keys=True)

    def hash(self) -> str:
        return hashlib.sha256(self.yaml_text().encode()).hexdigest()


def load_strategy_config(strategy_path: Path, root: Path) -> Resolved:
    from mb.strategy.registry import params_model

    strategy_path = strategy_path.resolve()
    raw = _read_yaml(strategy_path)
    strategy = _validate(StrategyConfig, raw, str(strategy_path))
    try:
        pmodel = params_model(strategy.name)
    except KeyError:
        raise ConfigError(f"unknown strategy '{strategy.name}'") from None
    params = _validate(pmodel, strategy.params, f"{strategy_path} (params)")
    market_path = root / "configs" / "market" / f"{strategy.market}.yaml"
    market = _validate(MarketConfig, _read_yaml(market_path), str(market_path))
    base_path = root / "configs" / "baselines.yaml"
    baselines = _validate(BaselinesConfig, _read_yaml(base_path), str(base_path))
    return Resolved(strategy, params, market, baselines, strategy_path)


def enforce_lock(cfg: Resolved, final: bool) -> None:
    """The locked test period is off limits unless --final is given."""
    lock = cfg.baselines.locked_from
    if cfg.strategy.period.end >= lock and not final:
        raise ConfigError(
            f"period.end {cfg.strategy.period.end} reaches the locked period (from {lock}); "
            "use --final for a final evaluation"
        )
