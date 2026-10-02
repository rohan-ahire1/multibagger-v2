"""Maps strategy name -> (params model, runner). Add strategies here."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

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


def _momentum() -> tuple[Any, Callable[[Resolved, Path], RunResult]]:
    from mb.strategy.momentum import run

    # A config validates as exactly one of these (unknown keys fail), so pre-M8 configs keep their hash.
    return run.Params | run.ParamsM8 | run.ParamsM10 | run.ParamsM11 | run.ParamsM12 | run.ParamsM13 | run.ParamsM19 | run.ParamsM21 | run.ParamsM22 | run.ParamsM27 | run.ParamsM29 | run.ParamsM32 | run.ParamsM40 | run.ParamsM44 | run.ParamsM46 | run.ParamsM53 | run.ParamsM55 | run.ParamsM57 | run.ParamsM75 | run.ParamsM76, run.run


def _blend() -> tuple[type[BaseModel], Callable[[Resolved, Path], RunResult]]:
    from mb.strategy.blend import run

    return run.Params, run.run


def _vcp() -> tuple[type[BaseModel], Callable[[Resolved, Path], RunResult]]:
    from mb.strategy.vcp import run

    return run.Params, run.run


_REGISTRY: dict[str, Callable[[], tuple[Any, Callable]]] = {
    "dummy": _dummy, "sepa": _sepa, "momentum": _momentum, "blend": _blend, "vcp": _vcp,
}


def params_model(name: str) -> Any:
    """A params model class, or a union of them."""
    return _REGISTRY[name]()[0]


def runner(name: str) -> Callable[[Resolved, Path], RunResult]:
    return _REGISTRY[name]()[1]
