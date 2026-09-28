"""Smoke-test strategy: takes no parameters and never trades."""
from __future__ import annotations

import polars as pl

from mb.config.loader import Resolved
from mb.config.models import Strict
from mb.runs.record import RunResult

TRADE_SCHEMA = {"symbol": pl.String, "entry_date": pl.Date, "exit_date": pl.Date, "return_pct": pl.Float64}
EQUITY_SCHEMA = {"date": pl.Date, "equity": pl.Float64}


class Params(Strict):
    pass


def run(cfg: Resolved) -> RunResult:
    return RunResult(
        metrics={"strategy": {"trades": 0}, "baselines": {}},
        trades=pl.DataFrame(schema=TRADE_SCHEMA),
        equity=pl.DataFrame(schema=EQUITY_SCHEMA),
    )
