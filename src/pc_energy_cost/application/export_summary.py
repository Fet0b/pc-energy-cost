"""Caso de uso: montar o resumo de custo de uma sessão e entregá-lo à porta de exportação."""

from __future__ import annotations

from dataclasses import replace

from ..domain.energy_estimation.schedule import load_zone
from ..domain.shared.errors import DomainError
from ..domain.usage_session.lifecycle import summarize
from ..domain.usage_session.model import ExportOutcome
from .ports import SessionLedger, SummaryExporter, TariffSource
from .resolve_tariff import TariffRequest, resolve_rate
from .session_report import pieces_for, to_summary_slices


def export_summary(
    session_id: int,
    ledger: SessionLedger,
    exporter: SummaryExporter,
    tariff: TariffRequest | None,
    source: TariffSource | None,
) -> ExportOutcome:
    found = ledger.get(session_id)
    if found is None:
        raise DomainError("session_not_found", f"sessão {session_id} não encontrada")
    session, acc = found
    summary = summarize(session, acc)
    if tariff is not None:
        selection = resolve_rate(tariff, source)  # type: ignore[arg-type]
        pieces = pieces_for(session, acc, selection, load_zone())
        summary = replace(summary, slices=to_summary_slices(pieces))
    return exporter.export(summary)
