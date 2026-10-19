"""Estimativa de custo: divisão por vigências, composição da taxa e CostEstimate."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..metering.model import ExcludedInterval, Scope
from ..shared.errors import DomainError
from ..shared.money import MoneyBRL
from ..shared.units import CTX, KWh, UnitRateBRLPerKWh, Watts
from ..tariff_catalog.model import Provenance
from .schedule import load_zone


@dataclass(frozen=True)
class RateWindow:
    """Tarifa base válida a partir de um dia; `last_day` (inclusivo) None = sem fim."""

    rate: UnitRateBRLPerKWh
    last_day: date | None = None
    projected: bool = False
    provenance: Provenance | None = None


RateLookup = Callable[[date], RateWindow]


@dataclass(frozen=True)
class RateExtras:
    """Adicional em R$/kWh somado à tarifa base e inclusões declaradas na tarifa base."""

    adicional: UnitRateBRLPerKWh
    tipo: str | None = None
    inclusoes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RateSlice:
    start: datetime
    end: datetime
    window: RateWindow

    def seconds(self) -> Decimal:
        delta = self.end.astimezone(timezone.utc) - self.start.astimezone(timezone.utc)
        return Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / Decimal(
            1_000_000
        )


@dataclass(frozen=True)
class SliceEnergy:
    slice: RateSlice
    energy: KWh

    @property
    def rate(self) -> Decimal:
        return self.slice.window.rate.value


@dataclass(frozen=True)
class CostEstimate:
    energy: KWh
    taxa_total: Decimal
    tarifa_base: Decimal
    adicional: Decimal
    adicional_tipo: str | None
    inclusoes_declaradas: tuple[str, ...]
    cost: MoneyBRL  # total arredondado (HALF_UP, 2 casas)
    cost_unrounded: Decimal
    warnings: tuple[str, ...]
    scope: Scope
    requested_duration: timedelta
    coverage_duration: timedelta
    excluded_duration: timedelta
    excluded_intervals: tuple[ExcludedInterval, ...]
    partial_data: bool
    slices: tuple[SliceEnergy, ...]
    provenance: tuple[Provenance, ...]


def split_by_vigencia(
    start: datetime, end: datetime, lookup: RateLookup, zone: ZoneInfo | None = None
) -> tuple[RateSlice, ...]:
    """Divide [início, fim) nas viradas de vigência (meia-noite local do dia seguinte ao fim)."""
    zone = zone or load_zone()
    for dt in (start, end):
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise DomainError("invalid_interval", "datas da estimativa precisam de fuso")
    s, e = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    if e < s:
        raise DomainError("invalid_interval", "o fim do intervalo deve ser posterior ao início")
    if e == s:
        zs = s.astimezone(zone)
        return (RateSlice(zs, zs, lookup(zs.date())),)
    out: list[RateSlice] = []
    cur = s
    while cur < e:
        window = lookup(cur.astimezone(zone).date())
        nxt = e
        if window.last_day is not None:
            boundary = datetime.combine(
                window.last_day + timedelta(days=1), time(0), tzinfo=zone
            ).astimezone(timezone.utc)
            nxt = min(e, boundary)
        if nxt <= cur:
            raise ValueError("lookup devolveu vigência que não cobre o dia consultado")
        out.append(RateSlice(cur.astimezone(zone), nxt.astimezone(zone), window))
        cur = nxt
    return tuple(out)


def assemble_estimate(
    parts: Sequence[SliceEnergy],
    extras: RateExtras,
    scope: Scope,
    requested: timedelta,
    coverage: timedelta,
    excluded: timedelta,
    excluded_intervals: Sequence[ExcludedInterval] = (),
    warnings: Sequence[str] = (),
) -> CostEstimate:
    """Soma energia e custo das fatias em Decimal; arredonda só o custo final (D6)."""
    if not parts:
        raise ValueError("estimativa sem fatias")
    extra = extras.adicional.value
    total_kwh = Decimal(0)
    weighted = Decimal(0)
    money = []
    for p in parts:
        total_kwh = CTX.add(total_kwh, p.energy.value)
        weighted = CTX.add(weighted, CTX.multiply(p.energy.value, p.rate))
        money.append(MoneyBRL(CTX.multiply(p.energy.value, CTX.add(p.rate, extra))))
    distinct = {p.rate for p in parts}
    if len(distinct) == 1:
        base = parts[0].rate
    elif total_kwh > 0:
        base = CTX.divide(weighted, total_kwh)
    else:
        base = parts[0].rate
    taxa_total = CTX.add(base, extra)
    partial = excluded > timedelta(0)
    notes = list(warnings)
    if any(p.slice.window.projected for p in parts):
        notes.append("projected_tariff")
    if taxa_total == 0:
        notes.append("zero_rate")
    if partial:
        notes.append("partial_data")
    provenance: list[Provenance] = []
    for p in parts:
        prov = p.slice.window.provenance
        if prov is not None and prov not in provenance:
            provenance.append(prov)
    return CostEstimate(
        energy=KWh(total_kwh),
        taxa_total=taxa_total,
        tarifa_base=base,
        adicional=extra,
        adicional_tipo=extras.tipo,
        inclusoes_declaradas=extras.inclusoes,
        cost=MoneyBRL.total(money),
        cost_unrounded=sum((m.value for m in money), Decimal(0)),
        warnings=tuple(dict.fromkeys(notes)),
        scope=scope,
        requested_duration=requested,
        coverage_duration=coverage,
        excluded_duration=excluded,
        excluded_intervals=tuple(excluded_intervals),
        partial_data=partial,
        slices=tuple(parts),
        provenance=tuple(provenance),
    )


def energy_for_slice(watts: Watts, piece: RateSlice) -> KWh:
    """kWh = W × segundos / 3600 / 1000, sem arredondar a duração."""
    return KWh(CTX.divide(CTX.multiply(watts.value, piece.seconds()), Decimal(3_600_000)))


def estimate_average_power(
    watts: Watts,
    start: datetime,
    end: datetime,
    lookup: RateLookup,
    extras: RateExtras,
    scope: Scope = Scope.MANUAL,
    zone: ZoneInfo | None = None,
) -> CostEstimate:
    """Potência média constante em [início, fim), dividida por vigências."""
    pieces = split_by_vigencia(start, end, lookup, zone)
    parts = [SliceEnergy(p, energy_for_slice(watts, p)) for p in pieces]
    total = sum((p.end.astimezone(timezone.utc) - p.start.astimezone(timezone.utc) for p in pieces), timedelta(0))
    return assemble_estimate(parts, extras, scope, total, total, timedelta(0))
