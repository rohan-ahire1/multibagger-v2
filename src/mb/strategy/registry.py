"""Maps strategy name -> (params model, runner). Add strategies here."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from mb.runs.record import RunResult
    from mb.config.loader import Resolved


def _dummy() -> tuple[type[BaseModel], Callable[[Resolved, Path], RunResult]]:
    from mb.strategy import dummy

    return dummy.Params, dummy.run


def _sepa() -> tuple[type[BaseModel], Callable[[Resolved, Path], RunResult]]:
    from mb.strategy.sepa import run

    return run.Params, run.run


def _momentum() -> tuple[type[BaseModel], Callable[[Resolved, Path], RunResult]]:
    from mb.strategy.momentum import run

    return run.Params, run.run


def _blend() -> tuple[type[BaseModel], Callable[[Resolved, Path], RunResult]]:
    from mb.strategy.blend import run

    return run.Params, run.run


_REGISTRY: dict[str, Callable[[], tuple[type[BaseModel], Callable]]] = {
    "dummy": _dummy, "sepa": _sepa, "momentum": _momentum, "blend": _blend,
}


def params_model(name: str) -> type[BaseModel]:
    return _REGISTRY[name]()[0]


def runner(name: str) -> Callable[[Resolved, Path], RunResult]:
    return _REGISTRY[name]()[1]
