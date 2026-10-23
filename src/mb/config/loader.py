from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, TypeAdapter, ValidationError

from mb.config.models import (BaselinesConfig, DataConfig, DataConfigM14, DataConfigM40, FoBhavSource, HarvestConfig, IndustrySource, LiveConfig, PledgeSource, MarketConfig,
                              PaperConfig, StrategyConfig, TaxConfig)


class ConfigError(Exception):
    pass


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    return data


def _validate(model: Any, data: dict[str, Any], where: str) -> Any:
    """`model` is a model class or a union of them."""
    try:
        return TypeAdapter(model).validate_python(data)
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
    baselines = load_baselines(root)
    return Resolved(strategy, params, market, baselines, strategy_path)


def load_baselines(root: Path) -> BaselinesConfig:
    path = root / "configs" / "baselines.yaml"
    return _validate(BaselinesConfig, _read_yaml(path), str(path))


def enforce_lock(cfg: Resolved, final: bool) -> None:
    """The locked test period is off limits unless --final is given.

    A run reads bars for `settle_calendar_days` past `period.end` so late exits close; that window counts as reaching in.
    """
    lock = cfg.baselines.locked_from
    engine = getattr(cfg.params, "engine", None)
    reach = cfg.strategy.period.end + timedelta(days=engine.settle_calendar_days if engine is not None else 0)
    if reach >= lock and not final:
        raise ConfigError(
            f"period.end {cfg.strategy.period.end} (plus settle window: {reach}) reaches the locked period (from {lock}); "
            "use --final for a final evaluation"
        )


def load_paper_config(path: Path, root: Path) -> tuple[PaperConfig, Resolved]:
    """The paper config and its strategy config, which must still resolve to the pinned hash and be a momentum config."""
    cfg = _validate(PaperConfig, _read_yaml(path.resolve()), str(path))
    strat = load_strategy_config(root / cfg.strategy_config, root)
    if strat.strategy.name != "momentum":
        raise ConfigError(f"{cfg.strategy_config}: paper trading supports momentum configs only")
    if strat.hash() != cfg.strategy_config_hash:
        raise ConfigError(f"{cfg.strategy_config} resolves to hash {strat.hash()[:12]}, not the pinned "
                          f"{cfg.strategy_config_hash[:12]}; a changed strategy needs a new paper config")
    return cfg, strat


def load_data_config(path: Path) -> tuple[DataConfig, str]:
    """Returns the validated data config and its hash."""
    cfg = _validate(DataConfig | DataConfigM14 | DataConfigM40, _read_yaml(path.resolve()), str(path))
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=True)
    return cfg, hashlib.sha256(text.encode()).hexdigest()


def load_tax_config(path: Path) -> TaxConfig:
    return _validate(TaxConfig, _read_yaml(path), str(path))


def load_industry_config(path: Path) -> IndustrySource:
    return _validate(IndustrySource, _read_yaml(path), str(path))


def load_pledge_config(path: Path) -> PledgeSource:
    return _validate(PledgeSource, _read_yaml(path), str(path))


def load_fo_bhav_config(path: Path) -> FoBhavSource:
    return _validate(FoBhavSource, _read_yaml(path), str(path))


def load_harvest_config(path: Path) -> HarvestConfig:
    return _validate(HarvestConfig, _read_yaml(path), str(path))


def load_live_config(path: Path) -> LiveConfig:
    return _validate(LiveConfig, _read_yaml(path.resolve()), str(path))
