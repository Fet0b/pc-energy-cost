"""Potência média informada manualmente (escopo `manual`)."""

from __future__ import annotations

from ...domain.metering.model import Available, Sample, Scope, Unavailable
from ...domain.shared.parsing import parse_watts
from ...domain.shared.units import Watts


class ManualAverageWatts:
    """Valor único em watts; 0 W é válido. Não há série temporal, logo `read()` é vazio."""

    def __init__(self, text: str) -> None:
        self.watts: Watts = parse_watts(text)

    def availability(self) -> Available | Unavailable:
        return Available(Scope.MANUAL)

    def read(self) -> tuple[Sample, ...]:
        return ()
