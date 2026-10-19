"""Caso de uso: medir potência por um provider; indisponível nunca vira zero."""

from __future__ import annotations

from dataclasses import dataclass

from datetime import datetime

from ..domain.metering.model import Available, ExcludedInterval, Sample, Scope, Unavailable
from ..domain.metering.ports import (
    ExcludingMeteringProvider,
    MeteringProvider,
    WindowedMeteringProvider,
)
from ..domain.shared.errors import UnavailableError


@dataclass(frozen=True)
class MeasureResult:
    scope: Scope
    warnings: tuple[str, ...]
    samples: tuple[Sample, ...]
    excluded: tuple[ExcludedInterval, ...] = ()
    window: tuple[datetime, datetime] | None = None


def measure_power(provider: MeteringProvider) -> MeasureResult:
    availability = provider.availability()
    if isinstance(availability, Unavailable):
        raise UnavailableError(f"telemetria indisponível: {availability.reason}")
    assert isinstance(availability, Available)
    # `InsufficientCoverage` do provider (contador ⇒ exit 6) propaga sem tratamento
    samples = tuple(provider.read())
    # extensões opcionais, lidas DEPOIS de `read()` (o provider de contador amostra no read)
    excluded = provider.excluded_intervals() if isinstance(provider, ExcludingMeteringProvider) else ()
    window = provider.window() if isinstance(provider, WindowedMeteringProvider) else None
    return MeasureResult(availability.scope, availability.warnings, samples, excluded, window)
