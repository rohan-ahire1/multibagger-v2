"""Dashboard config: which runs and paper books go into the bundle, and how compact it is. Every value is in the YAML."""
from __future__ import annotations

from pathlib import Path

from pydantic import model_validator

from mb.config.loader import ConfigError, _read_yaml, _validate
from mb.config.models import Strict


class RunEntry(Strict):
    run: str | None = None   # a run id, or
    pin: str | None = None   # a milestone name from <runs_dir>/pins.json; exactly one of the two
    label: str
    group: str            # one of DashboardConfig.groups
    note: str | None = None
    tag: str | None = None   # badge in the picker; null = "Final" for final runs, "Dev" otherwise

    @model_validator(mode="after")
    def _one_source(self) -> RunEntry:
        if (self.run is None) == (self.pin is None):
            raise ValueError(f"run '{self.label}': give exactly one of run and pin")
        return self


class Bundle(Strict):
    equity_decimals: int          # rounding of equity values
    price_decimals: int           # rounding of weekly prices and trade prices
    chart_weeks_before: int       # weeks of price history the trade chart shows before entry
    chart_weeks_after: int        # ... and after exit; prices are exported for these windows only


class PaperBook(Strict):
    config: str                   # configs/paper/<name>.yaml
    label: str
    backtest_run: str             # the run whose numbers are this book's expectation
    timer_file: str               # deploy/*.timer, read for the schedule text


class Paper(Strict):
    preview_dataset: str          # dataset ref the target-book preview is ranked on, e.g. nse_research@2026-09-29d
    next_in_line: int             # names shown after the top N
    recent_fills: int             # fills listed for a live book
    books: list[PaperBook]


class DashboardConfig(Strict):
    name: str
    output: str                   # bundle path, relative to --root
    runs_dir: str                 # relative to the data root
    sector_map: str               # relative to --root
    groups: list[str]             # picker sections, in order
    bundle: Bundle
    paper: Paper
    runs: list[RunEntry]

    @model_validator(mode="after")
    def _groups_known(self) -> DashboardConfig:
        bad = sorted({r.group for r in self.runs} - set(self.groups))
        if bad:
            raise ValueError(f"runs use groups that are not listed: {', '.join(bad)}")
        return self


def load(path: Path) -> DashboardConfig:
    return _validate(DashboardConfig, _read_yaml(path.resolve()), str(path))


__all__ = ["ConfigError", "DashboardConfig", "load"]
