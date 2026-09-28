"""Maps strategy name -> (params model, runner). Add strategies here."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from mb.runs.record import RunResult
    from mb.config.loader import Resolved


def _dummy() -> tuple[type[BaseModel], Callable[[Resolved], RunResult]]:
    from mb.strategy import dummy

    return dummy.Params, dummy.run


_REGISTRY: dict[str, Callable[[], tuple[type[BaseModel], Callable]]] = {"dummy": _dummy}


def params_model(name: str) -> type[BaseModel]:
    return _REGISTRY[name]()[0]


def runner(name: str) -> Callable[[Resolved], RunResult]:
    return _REGISTRY[name]()[1]
