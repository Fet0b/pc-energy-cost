"""Agenda de uso: intervalos [início, fim) tz-aware em America/Sao_Paulo (D1, D9)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.domain.shared.units import CTX, Duration

ZONE_NAME = "America/Sao_Paulo"


def load_zone(loader: Callable[[str], ZoneInfo] = ZoneInfo) -> ZoneInfo:
    """Carrega o fuso; sem base IANA nem tzdata ⇒ timezone_data_missing (nunca UTC-3 fixo)."""
    try:
        return loader(ZONE_NAME)
    except ZoneInfoNotFoundError as exc:
        raise DomainError(
            "timezone_data_missing",
            f"base de fusos IANA indisponível para {ZONE_NAME}; instale o pacote tzdata",
        ) from exc


def duration_between(start: datetime, end: datetime) -> Duration:
    """Duração real (via UTC) em horas, arredondada às 4 casas de D14."""
    seconds = Decimal((end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds())
    hours = CTX.divide(seconds, Decimal(3600))
    return Duration(hours.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP, context=CTX))


class Interval:
    """Intervalo [início, fim); datetimes naive são interpretados no fuso (padrão São Paulo)."""

    def __init__(self, start: datetime, end: datetime, zone: ZoneInfo | None = None) -> None:
        zone = zone or load_zone()
        self.start = start if start.tzinfo else start.replace(tzinfo=zone)
        self.end = end if end.tzinfo else end.replace(tzinfo=zone)
        if self.end.astimezone(timezone.utc) <= self.start.astimezone(timezone.utc):
            raise DomainError("invalid_interval", "o fim do intervalo deve ser posterior ao início")

    def duration(self) -> Duration:
        return duration_between(self.start, self.end)

    def _utc(self) -> tuple[datetime, datetime]:
        return self.start.astimezone(timezone.utc), self.end.astimezone(timezone.utc)


class Schedule:
    """Conjunto de intervalos sem sobreposição; adjacentes são válidos."""

    def __init__(self, intervals: Iterable[Interval]) -> None:
        ordered = sorted(intervals, key=lambda i: i._utc())
        for prev, cur in zip(ordered, ordered[1:]):
            if cur._utc()[0] < prev._utc()[1]:
                raise DomainError("overlapping_intervals", "intervalos da agenda se sobrepõem")
        self.intervals = tuple(ordered)

    def total_duration(self) -> Duration:
        total = sum(
            ((i._utc()[1] - i._utc()[0] for i in self.intervals)), timedelta(0)
        )
        hours = CTX.divide(Decimal(total.total_seconds()), Decimal(3600))
        return Duration(hours.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP, context=CTX))
