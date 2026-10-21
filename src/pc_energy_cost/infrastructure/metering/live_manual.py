"""Potência informada ou de cenário, ao vivo; toda leitura é rotulada `assumed`.

Mesma semântica de `_AssumedPowerMeter` (`application/track_session.py`).
"""

from __future__ import annotations

import time
from decimal import Decimal

from ...application.ports import LiveReading, MonotonicClock
from ...domain.metering.model import Available, Scope
from ...domain.shared.errors import InvalidInput
from ...domain.shared.units import CTX, Watts
from ...domain.usage_session.lifecycle import PROVISIONAL
from ...domain.usage_session.model import EnergyBasis

_NS = Decimal(1_000_000_000)


class _SystemMonotonic:
    def monotonic_ns(self) -> int:
        return time.monotonic_ns()


class LiveManualPower:
    def __init__(
        self,
        watts: Decimal | Watts,
        mono: MonotonicClock | None = None,
        basis: EnergyBasis = EnergyBasis.USER_POWER,
    ) -> None:
        if basis not in (EnergyBasis.USER_POWER, EnergyBasis.SCENARIO):
            raise InvalidInput("potência informada só aceita base user_power ou scenario")
        self._w = (watts if isinstance(watts, Watts) else Watts(watts)).value
        self._basis = basis
        self._mono = mono or _SystemMonotonic()
        self._last = self._mono.monotonic_ns()

    def availability(self) -> Available:
        return Available(Scope.SCENARIO if self._basis is EnergyBasis.SCENARIO else Scope.MANUAL)

    def max_tick_s(self) -> Decimal:
        return Decimal(PROVISIONAL.max_interval_s)

    def energy_basis(self) -> EnergyBasis:
        return self._basis

    def tick(self) -> LiveReading:
        now = self._mono.monotonic_ns()
        dur = Decimal(now - self._last) / _NS
        self._last = now
        return LiveReading(energy_wh=CTX.divide(CTX.multiply(self._w, dur), Decimal(3600)),
                           duration_s=dur, assumed=True)
