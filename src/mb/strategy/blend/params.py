"""Blend parameters: fixed-weight sleeves, each an existing strategy config pinned by its hash."""
from __future__ import annotations

import math
from typing import Literal

from pydantic import model_validator

from mb.config.models import Strict


class Sleeve(Strict):
    config: str                   # strategy config path, relative to the repo root
    config_hash: str              # its resolved-config hash (`mb backtest` prints it); a changed file is refused
    weight: float                 # share of initial capital; sleeves are never rebalanced against each other


class Params(Strict):
    sleeves: list[Sleeve]
    initial_capital: float

    @model_validator(mode="after")
    def _weights(self) -> Params:
        if len(self.sleeves) < 2:
            raise ValueError("a blend needs at least two sleeves")
        if any(s.weight <= 0 for s in self.sleeves) or not math.isclose(sum(s.weight for s in self.sleeves), 1.0):
            raise ValueError("sleeve weights must be positive and sum to 1")
        return self


class ParamsM110(Params):
    """M110 (docs/research/m110.md): `monthly` resets the sleeves to their weights at the close of each month's last
    session; the rupees moved pay the market's slippage and charges on both the sale and the purchase."""
    rebalance: Literal["none", "monthly"]
