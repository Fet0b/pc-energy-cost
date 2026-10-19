"""Seleção de tarifa B1 por vigência: dedupe de linhas idênticas, nunca soma nem escolha."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from ..shared.errors import DomainError
from .model import ResolvedTariff, SourceInfo, TariffProfile, TariffRecord


def _dedupe(records: Iterable[TariffRecord]) -> list[TariffRecord]:
    """Remove só linhas totalmente idênticas, preservando a ordem."""
    return list(dict.fromkeys(records))


def list_vigencias(records: Iterable[TariffRecord], profile: TariffProfile) -> list[TariffRecord]:
    """Registros do perfil (dedupe), ordenados por vigência, sem filtrar por data."""
    matching = _dedupe(r for r in records if profile.matches(r))
    return sorted(matching, key=lambda r: (r.inicio, r.fim))


def select_tariff(
    records: Iterable[TariffRecord], profile: TariffProfile, day: date
) -> TariffRecord:
    vigencias = list_vigencias(records, profile)
    if not vigencias:
        raise DomainError(
            "tariff_not_found", "nenhuma tarifa do perfil existe para o CNPJ informado"
        )
    in_effect = [r for r in vigencias if r.covers(day)]
    if not in_effect:
        last = max(r.fim for r in vigencias)
        raise DomainError(
            "tariff_not_in_effect",
            f"nenhuma vigência cobre {day.isoformat()} (última vigência termina em {last.isoformat()})",
        )
    if len(in_effect) > 1:
        raise DomainError(
            "tariff_ambiguous",
            f"{len(in_effect)} registros distintos cobrem {day.isoformat()}",
        )
    return in_effect[0]


def resolve_tariff(
    records: Iterable[TariffRecord], profile: TariffProfile, day: date, source: SourceInfo
) -> ResolvedTariff:
    return ResolvedTariff.build(select_tariff(records, profile, day), profile, source)
