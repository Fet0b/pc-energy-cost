"""Integração de potência por degraus (padrão) ou trapézio, com regras de cobertura."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from ..metering.model import ExcludedInterval, Sample, SampleUnit
from ..shared.errors import InsufficientCoverage, InvalidInput
from ..shared.units import CTX, Wh

DEFAULT_MAX_GAP = timedelta(minutes=5)
MIN_MAX_GAP = timedelta(seconds=1)
MAX_MAX_GAP = timedelta(hours=24)
METHODS = ("steps", "trapezoid")

# segmento linear coberto: (início, watts_início, fim, watts_fim)
_Seg = tuple[datetime, Decimal, datetime, Decimal]


@dataclass(frozen=True)
class IntegrationResult:
    energy: Wh
    requested_duration: timedelta
    coverage_duration: timedelta
    excluded_duration: timedelta
    excluded_intervals: tuple[ExcludedInterval, ...]
    partial_data: bool
    warnings: tuple[str, ...] = ()


def _secs(d: timedelta) -> Decimal:
    return Decimal(d.days * 86400 + d.seconds) + Decimal(d.microseconds) / Decimal(1_000_000)


def _value_at(seg: _Seg, t: datetime) -> Decimal:
    a, va, b, vb = seg
    if va == vb or t == a:
        return va
    return va + (vb - va) * _secs(t - a) / _secs(b - a)


def _clip(seg: _Seg, lo: datetime, hi: datetime) -> _Seg | None:
    a, _, b, _ = seg
    start, end = max(a, lo), min(b, hi)
    if end <= start:
        return None
    return (start, _value_at(seg, start), end, _value_at(seg, end))


def _subtract(
    ranges: list[tuple[datetime, datetime]], cut: tuple[datetime, datetime]
) -> list[tuple[datetime, datetime]]:
    out = []
    for a, b in ranges:
        if cut[1] <= a or cut[0] >= b:
            out.append((a, b))
            continue
        if a < cut[0]:
            out.append((a, cut[0]))
        if cut[1] < b:
            out.append((cut[1], b))
    return out


def _prepare(samples: list[Sample]) -> tuple[list[Sample], tuple[str, ...]]:
    for s in samples:
        if s.unit is not SampleUnit.WATTS:
            raise InvalidInput("integrate_power aceita somente amostras de potência (W)")
        if s.timestamp.tzinfo is None or s.timestamp.utcoffset() is None:
            raise InvalidInput("amostra com timestamp sem fuso")
    warnings: tuple[str, ...] = ()
    ordered = sorted(samples, key=lambda s: s.timestamp)
    if ordered != samples:
        warnings = ("out_of_order",)
    unique: list[Sample] = []
    for s in ordered:
        if unique and unique[-1].timestamp == s.timestamp:
            if unique[-1].quantity != s.quantity:
                raise InvalidInput(
                    f"timestamp duplicado com valores distintos: {s.timestamp.isoformat()}",
                    code="csv_conflicting_duplicate",
                )
            continue
        unique.append(s)
    return unique, warnings


def integrate_power(
    samples,
    window_start: datetime,
    window_end: datetime,
    max_gap: timedelta = DEFAULT_MAX_GAP,
    method: str = "steps",
    pre_excluded: tuple[ExcludedInterval, ...] = (),
    source: str = "csv",
) -> IntegrationResult:
    if not MIN_MAX_GAP <= max_gap <= MAX_MAX_GAP:
        raise InvalidInput("max_gap fora da faixa de 1 s a 24 h")
    if method not in METHODS:
        raise InvalidInput(f"método de integração desconhecido: {method!r}")
    if window_end <= window_start:
        raise InvalidInput("janela com fim <= início", code="invalid_interval")
    pts, warnings = _prepare(list(samples))

    covered: list[_Seg] = []
    excluded: list[ExcludedInterval] = []

    def exclude(a: datetime, b: datetime, reason: str) -> None:
        a, b = max(a, window_start), min(b, window_end)
        if b > a:
            excluded.append(ExcludedInterval(a, b, reason))

    if not pts or pts[0].timestamp >= window_end:
        exclude(window_start, window_end, "no_sample")
    else:
        exclude(window_start, pts[0].timestamp, "no_sample")
        for cur, nxt in zip(pts, pts[1:]):
            if nxt.timestamp <= window_start or cur.timestamp >= window_end:
                continue
            if nxt.timestamp - cur.timestamp <= max_gap:
                end_v = nxt.quantity if method == "trapezoid" else cur.quantity
                seg = _clip((cur.timestamp, cur.quantity, nxt.timestamp, end_v),
                            window_start, window_end)
                if seg:
                    covered.append(seg)
            else:
                exclude(cur.timestamp, nxt.timestamp, "gap")
        last = pts[-1]
        if last.timestamp < window_end:
            if window_end - last.timestamp <= max_gap:
                seg = _clip((last.timestamp, last.quantity, window_end, last.quantity),
                            window_start, window_end)
                if seg:
                    covered.append(seg)
            else:
                exclude(last.timestamp, window_end, "gap")

    # intervalos pré-excluídos (ex.: RAPL): retirados da cobertura, sem contar duas vezes
    for pre in pre_excluded:
        a, b = max(pre.start, window_start), min(pre.end, window_end)
        if b <= a:
            continue
        new_cov: list[_Seg] = []
        for seg in covered:
            if b <= seg[0] or a >= seg[2]:
                new_cov.append(seg)
                continue
            for lo, hi in ((seg[0], a), (b, seg[2])):
                part = _clip(seg, lo, hi)
                if part:
                    new_cov.append(part)
        covered = new_cov
        fresh = [(a, b)]
        for ex in excluded:
            fresh = _subtract(fresh, (ex.start, ex.end))
        for fa, fb in fresh:
            excluded.append(ExcludedInterval(fa, fb, pre.reason))

    excluded.sort(key=lambda e: e.start)
    coverage = sum((seg[2] - seg[0] for seg in covered), timedelta(0))
    if coverage == timedelta(0):
        raise InsufficientCoverage("cobertura de medição nula na janela solicitada", source)
    watt_seconds = sum(
        (_secs(seg[2] - seg[0]) * (seg[1] + seg[3]) / Decimal(2) for seg in covered),
        Decimal(0),
    )
    energy = Wh(CTX.divide(watt_seconds, Decimal(3600)))
    excluded_duration = sum((e.end - e.start for e in excluded), timedelta(0))
    return IntegrationResult(
        energy=energy,
        requested_duration=window_end - window_start,
        coverage_duration=coverage,
        excluded_duration=excluded_duration,
        excluded_intervals=tuple(excluded),
        partial_data=excluded_duration > timedelta(0),
        warnings=warnings,
    )
