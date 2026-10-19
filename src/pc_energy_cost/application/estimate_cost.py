"""Caso de uso: potência × agenda/janela × tarifa ⇒ CostEstimate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..domain.energy_estimation.estimate import (
    CostEstimate,
    SliceEnergy,
    assemble_estimate,
    energy_for_slice,
    split_by_vigencia,
)
from ..domain.energy_estimation.integration import DEFAULT_MAX_GAP, integrate_power
from ..domain.energy_estimation.schedule import Schedule, load_zone
from ..domain.metering.model import ExcludedInterval, Sample, Scope
from ..domain.shared.errors import InsufficientCoverage, InvalidInput
from ..domain.shared.parsing import parse_hours, parse_max_gap, parse_watts
from .ports import Clock, TariffSource
from .resolve_tariff import RateSelection, TariffRequest, resolve_rate


@dataclass(frozen=True)
class EstimateRequest:
    tariff: TariffRequest
    potencia: str | None = None
    cenario_potencia_nominal: str | None = None
    samples: tuple[Sample, ...] | None = None
    horas: str | None = None
    schedule: Schedule | None = None
    inicio: datetime | None = None
    fim: datetime | None = None
    max_gap: str | None = None
    trapezio: bool = False
    # intervalos já excluídos pelo provider (ex.: contador RAPL), repassados à integração
    pre_excluded: tuple[ExcludedInterval, ...] = ()
    # origem da série para `insufficient_coverage`: "csv" ⇒ exit 2, "counter" ⇒ exit 6
    coverage_source: str = "csv"


def _aware(dt: datetime, zone: ZoneInfo) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=zone)


def _span(start: datetime, end: datetime) -> timedelta:
    return end.astimezone(timezone.utc) - start.astimezone(timezone.utc)


def estimate_cost(request: EstimateRequest, source: TariffSource, clock: Clock) -> CostEstimate:
    given = [
        request.potencia is not None,
        request.cenario_potencia_nominal is not None,
        request.samples is not None,
    ]
    if sum(given) != 1:
        raise InvalidInput(
            "informe exatamente uma fonte de potência: potência média, série ou cenário nominal"
        )
    zone = load_zone()
    selection = resolve_rate(request.tariff, source)
    if request.samples is not None:
        return _from_samples(request, selection, zone)

    scenario = request.cenario_potencia_nominal is not None
    watts = parse_watts(request.cenario_potencia_nominal if scenario else request.potencia)
    if request.schedule is not None:
        windows = [(i.start, i.end) for i in request.schedule.intervals]
    elif request.horas is not None:
        hours = parse_hours(request.horas).hours
        start = _aware(request.inicio, zone) if request.inicio else clock.now()
        micros = int(hours * Decimal(3_600_000_000))
        end = (start.astimezone(timezone.utc) + timedelta(microseconds=micros)).astimezone(zone)
        windows = [(start, end)]
    elif request.inicio is not None and request.fim is not None:
        windows = [(_aware(request.inicio, zone), _aware(request.fim, zone))]
    else:
        raise InvalidInput("informe agenda, --horas ou --inicio/--fim")
    parts = [
        SliceEnergy(piece, energy_for_slice(watts, piece))
        for start, end in windows
        for piece in split_by_vigencia(start, end, selection.lookup, zone)
    ]
    total = sum((_span(p.slice.start, p.slice.end) for p in parts), timedelta(0))
    return assemble_estimate(
        parts,
        selection.extras,
        Scope.SCENARIO if scenario else Scope.MANUAL,
        total,
        total,
        timedelta(0),
        (),
        selection.warnings,
    )


def _from_samples(request: EstimateRequest, selection: RateSelection, zone: ZoneInfo) -> CostEstimate:
    samples = request.samples or ()
    if request.inicio is not None:
        start = _aware(request.inicio, zone)
    elif samples:
        start = min(s.timestamp for s in samples)
    else:
        raise InvalidInput("série vazia: informe --inicio e --fim")
    if request.fim is not None:
        end = _aware(request.fim, zone)
    elif samples:
        end = max(s.timestamp for s in samples)
    else:
        raise InvalidInput("série vazia: informe --inicio e --fim")
    max_gap = parse_max_gap(request.max_gap) if request.max_gap else DEFAULT_MAX_GAP
    method = "trapezoid" if request.trapezio else "steps"

    parts: list[SliceEnergy] = []
    intervals: list[ExcludedInterval] = []
    warnings: list[str] = list(selection.warnings)
    requested = coverage = excluded = timedelta(0)
    first_error: InsufficientCoverage | None = None
    for piece in split_by_vigencia(start, end, selection.lookup, zone):
        try:
            result = integrate_power(
                samples, piece.start, piece.end, max_gap, method, request.pre_excluded,
                request.coverage_source,
            )
        except InsufficientCoverage as exc:
            # fatia sem cobertura: excluída inteira; só falha se nenhuma fatia tiver cobertura
            first_error = first_error or exc
            span = _span(piece.start, piece.end)
            intervals.append(ExcludedInterval(piece.start, piece.end, "gap"))
            requested, excluded = requested + span, excluded + span
            continue
        parts.append(SliceEnergy(piece, result.energy.to_kwh()))
        intervals.extend(result.excluded_intervals)
        warnings.extend(result.warnings)
        requested += result.requested_duration
        coverage += result.coverage_duration
        excluded += result.excluded_duration
    if not parts:
        assert first_error is not None
        raise first_error
    return assemble_estimate(
        parts, selection.extras, Scope.MANUAL, requested, coverage, excluded, intervals, warnings
    )
