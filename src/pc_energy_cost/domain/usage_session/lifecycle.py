"""Ciclo de vida de sessões: funções puras, sem I/O e sem relógio próprio.

Todos os instantes e durações chegam como argumentos (relógios injetados pelo
chamador). Nada aqui afirma como um relógio específico se comporta em um SO.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Sequence

from ..metering.model import ExcludedInterval
from ..shared.errors import InvalidInput
from .model import Accumulator, EndReason, Session, SessionCostSummary

_ZERO = Decimal(0)


@dataclass(frozen=True)
class ProvisionalDefaults:
    """Padrões PROVISÓRIOS (REVIEW-9): propostos, NÃO medidos. Único lugar nomeado."""

    sample_interval_s: int = 5
    persist_interval_s: int = 60
    stale_factor: int = 3
    clock_tolerance_factor: int = 2
    liveness_factor: int = 2
    min_interval_s: int = 1
    max_interval_s: int = 3600

    def stale_after_s(self, sample_interval_s: int) -> Decimal:
        return Decimal(self.stale_factor * sample_interval_s)

    def clock_tolerance_s(self, sample_interval_s: int) -> Decimal:
        return Decimal(self.clock_tolerance_factor * sample_interval_s)

    def liveness_window_s(self, persist_interval_s: int) -> int:
        return self.liveness_factor * persist_interval_s


PROVISIONAL = ProvisionalDefaults()

# REVIEW-4: suspensão divide a sessão. Único ponto a mudar se a decisão mudar.
SUSPEND_SPLITS_SESSION = True


# ---------------------------------------------------------------- lacunas parede x monotônico

class GapKind(Enum):
    NONE = "none"
    SUSPEND = "suspend"
    CLOCK_DISCONTINUITY = "clock_discontinuity"


def classify_gap(wall_delta_s: Decimal, mono_delta_s: Decimal, sample_interval_s: int) -> GapKind:
    """Classifica o avanço entre dois tiques usando só os deltas recebidos.

    Parede recuou, ou monotônico avançou mais que a parede acima da tolerância:
    descontinuidade. Parede avançou além da tolerância e o delta monotônico
    ficou dentro da tolerância: suspensão provável. Parede avançou além da
    tolerância e o monotônico também avançou além dela: descontinuidade.
    Esta função não afirma como relógios reais se comportam durante uma
    suspensão em nenhum sistema operacional; isso não foi verificado.
    """
    tol = PROVISIONAL.clock_tolerance_s(sample_interval_s)
    if wall_delta_s < 0:
        return GapKind.CLOCK_DISCONTINUITY
    diff = wall_delta_s - mono_delta_s
    if abs(diff) <= tol:
        return GapKind.NONE
    if diff < 0:
        return GapKind.CLOCK_DISCONTINUITY
    return GapKind.SUSPEND if mono_delta_s <= tol else GapKind.CLOCK_DISCONTINUITY


@dataclass(frozen=True)
class GapResolution:
    kind: GapKind
    end_session_at: datetime | None = None
    end_reason: EndReason | None = None
    excluded: ExcludedInterval | None = None


def resolve_gap(kind: GapKind, anchor: datetime, mono_delta_s: Decimal) -> GapResolution:
    """Efeito de uma lacuna. `anchor` é `last_seen_utc` (suspensão) ou a parede do tique anterior.

    Descontinuidade: intervalo excluído com a duração do monotônico (nunca negativa,
    sem duplicar tempo). Suspensão: fecha em `anchor` (se SUSPEND_SPLITS_SESSION);
    o tempo suspenso não vira cobertura nem exclusão.
    """
    if kind is GapKind.CLOCK_DISCONTINUITY:
        if mono_delta_s <= 0:
            return GapResolution(kind)
        end = anchor + timedelta(microseconds=int(mono_delta_s * 1_000_000))
        if end <= anchor:
            return GapResolution(kind)
        return GapResolution(kind, excluded=ExcludedInterval(anchor, end, "clock_discontinuity"))
    if kind is GapKind.SUSPEND and SUSPEND_SPLITS_SESSION:
        return GapResolution(kind, end_session_at=anchor, end_reason=EndReason.SUSPEND)
    return GapResolution(kind)


# ---------------------------------------------------------------- recuperação

@dataclass(frozen=True)
class RecoveryDecision:
    alive: bool
    end_reason: EndReason | None = None
    end_at: datetime | None = None
    warning: str | None = None


def decide_recovery(session: Session, boot_id_now: str | None, now: datetime) -> RecoveryDecision:
    """Decide o destino de uma sessão aberta ao iniciar (S2).

    Ordem: boot diferente (reboot, qualquer idade); `last_seen_utc` no futuro
    (descontinuidade); idade >= 2 x persist_interval_s (queda); senão viva.
    O fim fica em [started_at, now]: duração nunca negativa.
    """
    end_at = max(session.started_at, min(session.last_seen_utc, now))
    boot_known = session.boot_id is not None and boot_id_now is not None
    if boot_known and session.boot_id != boot_id_now:
        return RecoveryDecision(False, EndReason.REBOOT_DETECTED, end_at)
    if session.last_seen_utc > now:
        return RecoveryDecision(False, EndReason.CLOCK_DISCONTINUITY, end_at)
    age = now - session.last_seen_utc
    limit = timedelta(seconds=PROVISIONAL.liveness_window_s(session.persist_interval_s))
    if age >= limit:
        warning = None if boot_known else (
            "sem identificação de boot: reinício indistinguível de queda; tratado como queda"
        )
        return RecoveryDecision(False, EndReason.CRASH_RECOVERED, end_at, warning)
    return RecoveryDecision(True)


# ---------------------------------------------------------------- acumulação

def accumulate_reading(
    acc: Accumulator, *, energy_wh: Decimal, duration_s: Decimal, assumed: bool = False
) -> Accumulator:
    if energy_wh < 0 or duration_s < 0:
        raise InvalidInput("leitura com energia ou duração negativa")
    if assumed:
        return replace(acc, assumed_wh=acc.assumed_wh + energy_wh,
                       covered_s=acc.covered_s + duration_s, stale=False)
    return replace(acc, measured_wh=acc.measured_wh + energy_wh,
                   covered_s=acc.covered_s + duration_s, stale=False)


def _merge(intervals: Sequence[ExcludedInterval]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for iv in sorted(intervals, key=lambda i: i.start):
        if merged and iv.start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], iv.end))
        else:
            merged.append((iv.start, iv.end))
    return merged


def _seconds(delta: timedelta) -> Decimal:
    return Decimal(delta // timedelta(microseconds=1)) / Decimal(1_000_000)


def exclusion_seconds(
    new: Sequence[ExcludedInterval], already_reported: Sequence[ExcludedInterval] = ()
) -> Decimal:
    """Segundos de `new` (união) que não se sobrepõem ao já relatado pelo adaptador."""
    total = _ZERO
    reported = _merge(already_reported)
    for start, end in _merge(new):
        covered = _ZERO
        for r_start, r_end in reported:
            lo, hi = max(start, r_start), min(end, r_end)
            if hi > lo:
                covered += _seconds(hi - lo)
        total += _seconds(end - start) - covered
    return total


def add_excluded(
    acc: Accumulator,
    intervals: Sequence[ExcludedInterval],
    already_reported: Sequence[ExcludedInterval] = (),
) -> Accumulator:
    secs = exclusion_seconds(intervals, already_reported)
    if secs == 0:
        return acc
    return replace(acc, excluded_s=acc.excluded_s + secs, partial_data=True)


def account_no_reading(
    acc: Accumulator, elapsed_s: Decimal, silence_s: Decimal, stale_after_s: Decimal
) -> Accumulator:
    """Tique sem leitura válida. Energia congelada; nunca extrapola nem preenche com zero.

    `silence_s` é o tempo desde a última leitura válida. Ao cruzar `stale_after_s`
    o silêncio inteiro vira excluído; depois disso, só o tempo decorrido.
    """
    if silence_s <= stale_after_s:
        return acc
    added = elapsed_s if acc.stale else silence_s
    return replace(acc, excluded_s=acc.excluded_s + added, partial_data=True, stale=True)


def summarize(session: Session, acc: Accumulator) -> SessionCostSummary:
    return SessionCostSummary(
        session_id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        measured_energy_kwh=acc.measured_wh / 1000,
        assumed_energy_kwh=acc.assumed_wh / 1000,
        covered_s=acc.covered_s,
        excluded_s=acc.excluded_s,
        partial_data=acc.partial_data,
        scope=session.scope,
        energy_basis=session.energy_basis,
    )
