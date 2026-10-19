"""Modelo de medição: amostras, escopos, disponibilidade e intervalos excluídos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from ..shared.errors import InvalidInput

EXCLUSION_REASONS = (
    "gap", "no_sample", "indeterminate_wrap", "clock_discontinuity",
    "counter_reset_or_invalid",
)


class SampleUnit(Enum):
    WATTS = "W"
    MICROJOULES = "uJ"  # energia acumulada (contador RAPL)
    WATT_HOURS = "Wh"  # energia acumulada


class Scope(Enum):
    WHOLE_SYSTEM_AC = "whole_system_ac"
    WHOLE_SYSTEM_UNVERIFIED = "whole_system_unverified"
    CPU_PACKAGE = "cpu_package"
    COMPONENT = "component"
    MANUAL = "manual"
    SCENARIO = "scenario"


@dataclass(frozen=True)
class Sample:
    timestamp: datetime
    quantity: Decimal
    unit: SampleUnit

    def __post_init__(self) -> None:
        if not isinstance(self.quantity, Decimal) or not self.quantity.is_finite():
            raise InvalidInput("amostra: quantidade deve ser Decimal finito")
        if self.quantity < 0:
            raise InvalidInput("amostra: quantidade negativa")
        if not isinstance(self.unit, SampleUnit):
            raise InvalidInput("amostra: unidade inválida")


@dataclass(frozen=True)
class Available:
    scope: Scope
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Unavailable:
    reason: str


@dataclass(frozen=True)
class ExcludedInterval:
    start: datetime
    end: datetime
    reason: str

    def __post_init__(self) -> None:
        if self.reason not in EXCLUSION_REASONS:
            raise ValueError(f"razão de exclusão desconhecida: {self.reason!r}")
        if self.end <= self.start:
            raise InvalidInput("intervalo excluído com fim <= início", code="invalid_interval")
