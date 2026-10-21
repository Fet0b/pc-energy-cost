"""Relatórios de sessões: listar e custo do período (estimativa, não fatura)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..domain.energy_estimation.estimate import split_by_vigencia
from ..domain.energy_estimation.schedule import load_zone
from ..domain.shared.errors import DomainError
from ..domain.shared.money import MoneyBRL
from ..domain.shared.units import CTX
from ..domain.usage_session.model import Accumulator, Session, SummarySlice
from .ports import SessionLedger, TariffSource
from .resolve_tariff import TariffRequest, resolve_rate

COST_LABEL = "estimativa da energia atribuível, não fatura"


@dataclass(frozen=True)
class SessionRow:
    session: Session
    acc: Accumulator


@dataclass(frozen=True)
class PeriodCost:
    since: datetime
    until: datetime
    sessions: int
    measured_kwh: Decimal
    assumed_kwh: Decimal
    measured_cost: MoneyBRL
    assumed_cost: MoneyBRL
    total_cost: MoneyBRL  # soma dos dois valores arredondados exibidos
    covered_s: Decimal
    excluded_s: Decimal
    partial_data: bool
    slices: tuple[SummarySlice, ...]
    label: str = COST_LABEL


@dataclass(frozen=True)
class _Piece:
    start: datetime
    end: datetime
    rate: Decimal
    measured_kwh: Decimal
    assumed_kwh: Decimal


def list_sessions(
    ledger: SessionLedger, since: datetime | None = None, until: datetime | None = None
) -> tuple[SessionRow, ...]:
    return tuple(SessionRow(s, a) for s, a in ledger.list_sessions(since, until))


def _span(session: Session) -> tuple[datetime, datetime]:
    return session.started_at, session.ended_at or session.last_seen_utc


def pieces_for(
    session: Session, acc: Accumulator, selection, zone: ZoneInfo,
    since: datetime | None = None, until: datetime | None = None,
) -> tuple[_Piece, ...]:
    """Reparte a energia da sessão (recortada ao período) pelas vigências, proporcional ao tempo.

    A energia acumulada não tem resolução no tempo: a repartição presume potência uniforme na
    sessão. Isso é uma aproximação, declarada aqui e no rótulo de estimativa.
    """
    start, end = _span(session)
    c_start = max(start, since) if since else start
    c_end = min(end, until) if until else end
    if c_end < c_start or (end > start and c_end == c_start):
        return ()
    total_s = Decimal((end - start).total_seconds())
    clip_s = Decimal((c_end - c_start).total_seconds())
    share = Decimal(1) if total_s == 0 else clip_s / total_s
    m_kwh, a_kwh = acc.measured_wh / 1000 * share, acc.assumed_wh / 1000 * share
    parts = split_by_vigencia(c_start, c_end, selection.lookup, zone)
    out = []
    for p in parts:
        frac = Decimal(1) if clip_s == 0 else p.seconds() / clip_s
        rate = CTX.add(p.window.rate.value, selection.extras.adicional.value)
        out.append(_Piece(p.start, p.end, rate, m_kwh * frac, a_kwh * frac))
    return tuple(out)


def to_summary_slices(pieces: tuple[_Piece, ...]) -> tuple[SummarySlice, ...]:
    return tuple(
        SummarySlice(p.start.date(), p.end.date(), p.measured_kwh, p.assumed_kwh, p.rate)
        for p in pieces
    )


def period_cost(
    ledger: SessionLedger, tariff: TariffRequest, source: TariffSource | None,
    since: datetime, until: datetime,
) -> PeriodCost:
    for dt in (since, until):
        if dt.tzinfo is None:
            raise DomainError("invalid_interval", "o período precisa de fuso")
    if until <= since:
        raise DomainError("invalid_interval", "o fim do período deve ser posterior ao início")
    selection = resolve_rate(tariff, source)  # type: ignore[arg-type]
    zone = load_zone()
    rows = ledger.list_sessions(since, until)
    pieces: list[_Piece] = []
    m_cost: list[MoneyBRL] = []
    a_cost: list[MoneyBRL] = []
    covered = excluded = Decimal(0)
    partial = False
    count = 0
    for session, acc in rows:
        got = pieces_for(session, acc, selection, zone, since, until)
        if not got:
            continue
        count += 1
        pieces.extend(got)
        for p in got:
            m_cost.append(MoneyBRL(CTX.multiply(p.measured_kwh, p.rate)))
            a_cost.append(MoneyBRL(CTX.multiply(p.assumed_kwh, p.rate)))
        covered += acc.covered_s
        excluded += acc.excluded_s
        partial = partial or acc.partial_data
    measured, assumed = MoneyBRL.total(m_cost), MoneyBRL.total(a_cost)
    return PeriodCost(
        since=since, until=until, sessions=count,
        measured_kwh=sum((p.measured_kwh for p in pieces), Decimal(0)),
        assumed_kwh=sum((p.assumed_kwh for p in pieces), Decimal(0)),
        measured_cost=measured, assumed_cost=assumed,
        total_cost=MoneyBRL(measured.rounded() + assumed.rounded()),
        covered_s=covered, excluded_s=excluded, partial_data=partial,
        slices=to_summary_slices(tuple(pieces)),
    )
