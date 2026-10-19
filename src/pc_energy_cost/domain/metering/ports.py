"""Porta de provedores de medição."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from datetime import datetime

from .model import Available, ExcludedInterval, Sample, Unavailable


class MeteringProvider(Protocol):
    def availability(self) -> Available | Unavailable: ...

    def read(self) -> tuple[Sample, ...]: ...


@runtime_checkable
class ExcludingMeteringProvider(MeteringProvider, Protocol):
    """Extensão OPCIONAL: provider que já excluiu intervalos (ex.: contador RAPL)."""

    def excluded_intervals(self) -> tuple[ExcludedInterval, ...]: ...


@runtime_checkable
class WindowedMeteringProvider(MeteringProvider, Protocol):
    """Extensão OPCIONAL: provider que conhece a janela medida (início, fim)."""

    def window(self) -> tuple[datetime, datetime]: ...
