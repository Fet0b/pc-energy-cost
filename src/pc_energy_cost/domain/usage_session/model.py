"""Modelo de sessões de uso: sessão, acumulador e resumo de custo (sem I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import NewType

from ..metering.model import Scope
from ..shared.errors import InvalidInput

SessionId = NewType("SessionId", int)


class EndReason(Enum):
    USER_STOP = "user_stop"
    SUSPEND = "suspend"
    REBOOT_DETECTED = "reboot_detected"
    CRASH_RECOVERED = "crash_recovered"
    CLOCK_DISCONTINUITY = "clock_discontinuity"


class EnergyBasis(Enum):
    MEASURED_COUNTER = "measured_counter"
    MEASURED_POWER = "measured_power"
    USER_POWER = "user_power"
    SCENARIO = "scenario"

    @property
    def is_measured(self) -> bool:
        return self in (EnergyBasis.MEASURED_COUNTER, EnergyBasis.MEASURED_POWER)


@dataclass(frozen=True)
class Accumulator:
    """Totais correntes de uma sessão. Energia em Wh e tempo em segundos (Decimal)."""

    measured_wh: Decimal = Decimal(0)
    assumed_wh: Decimal = Decimal(0)
    covered_s: Decimal = Decimal(0)
    excluded_s: Decimal = Decimal(0)
    partial_data: bool = False
    stale: bool = False


@dataclass(frozen=True)
class Session:
    id: int
    started_at: datetime
    last_seen_utc: datetime
    ended_at: datetime | None
    end_reason: EndReason | None
    boot_id: str | None
    sample_interval_s: int
    persist_interval_s: int
    scope: Scope
    energy_basis: EnergyBasis

    def __post_init__(self) -> None:
        for name in ("started_at", "last_seen_utc", "ended_at"):
            v = getattr(self, name)
            if v is not None and v.tzinfo is None:
                raise InvalidInput(f"sessão: {name} sem fuso")
        if self.ended_at is None:
            if self.end_reason is not None:
                raise InvalidInput("sessão aberta não tem end_reason")
            return
        if self.ended_at < self.started_at:
            raise InvalidInput("sessão com fim anterior ao início", code="invalid_interval")
        if self.end_reason is None:
            raise InvalidInput("sessão encerrada exige end_reason")

    @property
    def is_open(self) -> bool:
        return self.ended_at is None


@dataclass(frozen=True)
class SummarySlice:
    """Fatia do resumo por vigência de tarifa (calculada na camada de aplicação)."""

    start: date
    end: date
    measured_energy_kwh: Decimal
    assumed_energy_kwh: Decimal
    rate_brl_per_kwh: Decimal | None = None  # taxa vigente na fatia (com adicional), se resolvida


@dataclass(frozen=True)
class SessionCostSummary:
    session_id: int
    started_at: datetime
    ended_at: datetime | None
    measured_energy_kwh: Decimal
    assumed_energy_kwh: Decimal
    covered_s: Decimal
    excluded_s: Decimal
    partial_data: bool
    scope: Scope
    energy_basis: EnergyBasis
    slices: tuple[SummarySlice, ...] = ()

    def __post_init__(self) -> None:
        if self.measured_energy_kwh < 0 or self.assumed_energy_kwh < 0:
            raise InvalidInput("resumo: energia negativa")
        if self.measured_energy_kwh > 0 and not self.energy_basis.is_measured:
            raise InvalidInput("resumo: energia medida com base informada/cenário")

    def energy_breakdown(self) -> tuple[Decimal, Decimal, Decimal]:
        """(medida, assumida, soma): a soma só sai junto das partes."""
        return (
            self.measured_energy_kwh,
            self.assumed_energy_kwh,
            self.measured_energy_kwh + self.assumed_energy_kwh,
        )


@dataclass(frozen=True)
class ExportOutcome:
    truncated: bool
    delivered: bool
    detail: str = ""
