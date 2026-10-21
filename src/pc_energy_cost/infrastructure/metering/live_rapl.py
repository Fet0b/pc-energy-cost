"""Medidor RAPL ao vivo: só a leitura anterior (memória O(1)), escopo `cpu_package`.

Reutiliza a leitura de sysfs e a política `dt_max`/wrap de `LinuxRaplProvider`. Relata ele
mesmo os intervalos excluídos; o laço não os conta de novo.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from ...application.ports import LiveReading
from ...domain.metering.model import Available, ExcludedInterval, Unavailable
from ...domain.shared.errors import InvalidInput, UnavailableError
from ...domain.usage_session.model import EnergyBasis
from .linux_rapl import (
    CLOCK_TOLERANCE_S,
    DEFAULT_P_MAX_W,
    DEFAULT_ROOT,
    LinuxRaplProvider,
    CounterReadError,
    read_counter,
    utc_now,
)

_NS = Decimal(1_000_000_000)


class LiveRaplMeter:
    def __init__(
        self,
        root: Path = DEFAULT_ROOT,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_clock: Callable[[], datetime] = utc_now,
        max_watts: int = DEFAULT_P_MAX_W,
    ) -> None:
        self._provider = LinuxRaplProvider(root, monotonic_ns, wall_clock, max_watts)
        self._mono, self._wall = monotonic_ns, wall_clock
        self._p_max = Decimal(max_watts)
        self._prev: tuple[int, datetime, tuple[int, ...]] | None = None  # só a leitura anterior

    def availability(self) -> Available | Unavailable:
        return self._provider.availability()

    def max_tick_s(self) -> Decimal:
        return self._provider.sampling_interval_seconds

    def energy_basis(self) -> EnergyBasis:
        return EnergyBasis.MEASURED_COUNTER

    def tick(self) -> LiveReading:
        try:
            pkgs = self._provider.require_packages()
            counters = tuple(read_counter(p.path / "energy_uj") for p in pkgs)
        except (UnavailableError, CounterReadError):
            # sem leitura: nunca zero; o par não atravessa a falha (como `LiveWmiMeter`), senão
            # o laço contaria o mesmo silêncio como excluído e, depois, como coberto
            self._prev = None
            return LiveReading()
        mono, wall = self._mono(), self._wall()
        if wall.tzinfo is None or wall.utcoffset() is None:
            raise InvalidInput("relógio de parede sem fuso")
        prev, self._prev = self._prev, (mono, wall, counters)
        if prev is None or len(prev[2]) != len(counters):
            return LiveReading()
        p_mono, p_wall, p_counters = prev
        us = (mono - p_mono) // 1000
        if us <= 0:
            return LiveReading()
        dt = Decimal(mono - p_mono) / _NS
        start = wall - timedelta(microseconds=us)

        def excluded(reason: str) -> LiveReading:
            return LiveReading(excluded=ExcludedInterval(start, wall, reason))

        if any(dt > self._provider.dt_max_for_range(p.max_range) for p in pkgs):
            return excluded("indeterminate_wrap")
        if abs(dt - Decimal((wall - p_wall).total_seconds())) > CLOCK_TOLERANCE_S:
            return excluded("clock_discontinuity")
        total_uj = 0
        for pkg, a, b in zip(pkgs, p_counters, counters):
            delta = b - a if b >= a else b + pkg.max_range - a
            if Decimal(delta) / dt / Decimal(1_000_000) > self._p_max:
                return excluded("counter_reset_or_invalid")
            total_uj += delta
        return LiveReading(energy_wh=Decimal(total_uj) / Decimal(3600 * 1_000_000), duration_s=dt)
