"""Medidor WMI ao vivo: potência instantânea integrada por degraus, escopo `component`.

Nunca foi executado em Windows real (ver `windows_wmi.py`). Só a leitura anterior é guardada.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal

from ...application.ports import LiveReading
from ...domain.metering.model import Available, ExcludedInterval, Unavailable
from ...domain.shared.units import CTX
from ...domain.usage_session.model import EnergyBasis
from .windows_wmi import TIMEOUT_S, Runner, WindowsWmiProvider, _utc_now, run_powershell

_NS = Decimal(1_000_000_000)
# Valor NÃO medido: usa o timeout do subprocess como teto (REVIEW-9); não afirma o
# comportamento do Windows. Intervalo além do teto mais o próprio timeout vira lacuna.
MAX_TICK_S = Decimal(TIMEOUT_S)
_GAP_LIMIT_S = MAX_TICK_S + Decimal(TIMEOUT_S)


class LiveWmiMeter:
    def __init__(
        self,
        runner: Runner = run_powershell,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._provider = WindowsWmiProvider(runner=runner, wall_clock=wall_clock)
        self._mono, self._wall = monotonic_ns, wall_clock
        self._prev: tuple[int, Decimal] | None = None  # (monotônico, W) da leitura anterior

    def availability(self) -> Available | Unavailable:
        return self._provider.availability()

    def max_tick_s(self) -> Decimal:
        return MAX_TICK_S

    def energy_basis(self) -> EnergyBasis:
        return EnergyBasis.MEASURED_POWER

    def tick(self) -> LiveReading:
        watts = self._provider.instant_power()
        now = self._mono()
        if isinstance(watts, Unavailable):
            self._prev = None  # sem leitura: nada de zero, e o degrau não atravessa a falha
            return LiveReading()
        prev, self._prev = self._prev, (now, watts)
        if prev is None:
            return LiveReading()
        us = (now - prev[0]) // 1000
        if us <= 0:
            return LiveReading()
        dt = Decimal(now - prev[0]) / _NS
        if dt > _GAP_LIMIT_S:
            end = self._wall()
            return LiveReading(excluded=ExcludedInterval(end - timedelta(microseconds=us), end, "gap"))
        energy = CTX.divide(CTX.multiply(prev[1], dt), Decimal(3600))  # degrau: potência anterior
        return LiveReading(energy_wh=energy, duration_s=dt)
