"""Strict config models: no defaults, unknown keys are errors."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class MarketConfig(Strict):
    slippage_bps_per_side: float
    idle_cash_yield_annual: float


class BaselinesConfig(Strict):
    locked_from: date


class Period(Strict):
    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> Period:
        if self.end < self.start:
            raise ValueError("period.end is before period.start")
        return self


_DATASET_RE = re.compile(r"^[a-z0-9_]+@[A-Za-z0-9._-]+$")


class StrategyConfig(Strict):
    name: str
    version: str
    dataset: str
    market: str
    period: Period
    params: dict[str, Any]

    @field_validator("dataset")
    @classmethod
    def _pinned(cls, v: str) -> str:
        if not _DATASET_RE.match(v):
            raise ValueError("dataset must look like <name>@<version>")
        if v.split("@", 1)[1] == "latest":
            raise ValueError("dataset must be pinned; 'latest' is not allowed")
        return v
