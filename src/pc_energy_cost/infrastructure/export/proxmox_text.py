"""Exportador "Proxmox-compatível (texto)": texto simples pt-BR, sem rede nem credencial.

Não é integração oficial nem adaptador de API: apenas produz um texto que cabe em um campo
de descrição de até 8192. A unidade desse limite (caracteres ou bytes) NÃO foi verificada;
por escolha conservadora o texto respeita 8192 caracteres E 8192 bytes UTF-8.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from ...domain.shared.money import MoneyBRL
from ...domain.shared.units import CTX
from ...domain.usage_session.model import ExportOutcome, SessionCostSummary

PUBLIC_NAME = "Proxmox-compatível (texto)"
LIMIT = 8192
_TRUNCATED_LINE = "[texto truncado: linhas finais omitidas]"


def _kwh(v: Decimal) -> str:
    return f"{v:.3f}".replace(".", ",")


def _rate(v: Decimal) -> str:
    return f"{v:.6f}".replace(".", ",")


def _dur(seconds: Decimal) -> str:
    s = int(seconds)
    return f"{s // 3600} h {s % 3600 // 60:02d} min {s % 60:02d} s"


def _lines(s: SessionCostSummary) -> list[str]:
    measured, assumed, total = s.energy_breakdown()
    end = s.ended_at.isoformat() if s.ended_at else "em andamento"
    lines = [
        f"{PUBLIC_NAME}: custo de energia da sessão {s.session_id}",
        "Custo estimado: estimativa, não fatura",
        f"Período: {s.started_at.isoformat()} até {end}",
        f"Escopo: {s.scope.value}",
        f"Base da energia: {s.energy_basis.value}",
        f"Energia medida: {_kwh(measured)} kWh",
        f"Energia assumida: {_kwh(assumed)} kWh",
        f"Energia total: {_kwh(total)} kWh",
        f"Tempo coberto: {_dur(s.covered_s)}; excluído: {_dur(s.excluded_s)}",
    ]
    if s.partial_data:
        lines.append("Atenção: dados parciais (há intervalos sem leitura válida)")
    priced = [sl for sl in s.slices if sl.rate_brl_per_kwh is not None]
    if priced and len(priced) == len(s.slices):
        parts = [
            MoneyBRL(CTX.multiply(sl.measured_energy_kwh + sl.assumed_energy_kwh,
                                  sl.rate_brl_per_kwh))
            for sl in priced
            if sl.rate_brl_per_kwh is not None
        ]
        lines.append(f"Custo estimado: {MoneyBRL.total(parts).display()}")
        lines.append("Tarifa por vigência (taxa; energia; custo):")
        for sl, part in zip(priced, parts):
            assert sl.rate_brl_per_kwh is not None
            lines.append(
                f"  {sl.start.isoformat()} a {sl.end.isoformat()}: "
                f"R$ {_rate(sl.rate_brl_per_kwh)}/kWh; "
                f"{_kwh(sl.measured_energy_kwh + sl.assumed_energy_kwh)} kWh; {part.display()}"
            )
    else:
        lines.append("Custo estimado: indisponível (tarifa não resolvida)")
    return lines


def _fits(text: str, limit: int) -> bool:
    return len(text) <= limit and len(text.encode("utf-8")) <= limit


class ProxmoxCompatibleTextExporter:
    """Implementa `SummaryExporter`. Sem `sink`, o texto volta em `ExportOutcome.detail`."""

    def __init__(
        self,
        sink: Callable[[str], None] | None = None,
        destination: str = "",
        limit: int = LIMIT,
    ) -> None:
        self._sink, self._destination, self._limit = sink, destination, limit

    def render(self, summary: SessionCostSummary) -> tuple[str, bool]:
        lines = _lines(summary)
        text = "\n".join(lines)
        if _fits(text, self._limit):
            return text, False
        while lines and not _fits("\n".join([*lines, _TRUNCATED_LINE]), self._limit):
            lines.pop()  # linhas inteiras do final
        return "\n".join([*lines, _TRUNCATED_LINE]), True

    def export(self, summary: SessionCostSummary) -> ExportOutcome:
        text, truncated = self.render(summary)
        if self._sink is None:
            return ExportOutcome(truncated=truncated, delivered=False, detail=text)
        self._sink(text)
        return ExportOutcome(truncated=truncated, delivered=True, detail=self._destination)
