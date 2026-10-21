"""Texto pt-BR da CLI: determinístico, sem float em dinheiro."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from ...application.refresh_catalog import RefreshResult
from ...domain.energy_estimation.estimate import CostEstimate
from ...domain.location_supplier.model import SupplierLink
from ...domain.metering.model import Scope

LABEL = "estimativa da energia atribuível, não fatura"

_SCOPE = {
    Scope.WHOLE_SYSTEM_AC: "sistema inteiro (tomada AC)",
    Scope.WHOLE_SYSTEM_UNVERIFIED: "sistema inteiro (não verificado)",
    Scope.CPU_PACKAGE: "CPU (package), parcial em relação ao PC",
    Scope.COMPONENT: "componente, parcial em relação ao PC",
    Scope.MANUAL: "manual (potência informada)",
    Scope.SCENARIO: "cenário (potência nominal, não é medição)",
}

_WARNINGS = {
    "projected_tariff": "tarifa projetada: usa a última tarifa conhecida (fora da vigência)",
    "zero_rate": "taxa zero: custo R$ 0,00",
    "partial_data": "dados parciais: o custo cobre só a energia da parte coberta",
    "base_excludes_taxes_and_flags": "a tarifa base ANEEL não inclui tributos nem bandeiras",
}

_EXCLUSION = {
    "gap": "lacuna acima do máximo",
    "no_sample": "sem amostra",
    "indeterminate_wrap": "wrap indeterminado do contador",
    "clock_discontinuity": "descontinuidade do relógio",
    "counter_reset_or_invalid": "reset ou leitura inválida do contador",
}


def _rate(value: Decimal) -> str:
    text = f"{value:f}"
    if "." not in text:
        text += ".00"
    elif len(text.split(".")[1]) < 2:
        text += "0"
    return "R$ " + text.replace(".", ",") + "/kWh"


def _day(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _when(value: datetime) -> str:
    return value.strftime("%d/%m/%Y %H:%M:%S")


def _hours(age: timedelta) -> str:
    return f"{age.total_seconds() / 3600:.0f} h"


def _span(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h} h {m:02d} min {s:02d} s"


def render_catalog(result: RefreshResult) -> list[str]:
    lines = [f"Catálogo de tarifas: {result.label}"]
    if result.stale:
        lines.append("Atenção: dados vencidos usados por falta de rede (cache vencido).")
    elif result.refreshed:
        lines.append("Catálogo atualizado a partir da fonte oficial.")
    else:
        lines.append("Catálogo em cache ainda válido (sem novo download).")
    lines.append(f"Idade dos dados: {_hours(result.age)}")
    if result.vigencia is not None:
        lines.append(f"Vigência das tarifas: {_day(result.vigencia[0])} a {_day(result.vigencia[1])}")
    if result.tariffs_loaded is not None:
        lines.append(f"Registros de tarifa carregados: {result.tariffs_loaded}")
    return lines


def render_refresh(result: RefreshResult) -> str:
    return "\n".join(render_catalog(result)) + "\n"


def render_supplier(link: SupplierLink) -> str:
    d, m = link.distributor, link.municipality
    return f"Distribuidora: {d.sig_agente} (CNPJ {d.cnpj}), município {m.name}/{m.uf} ({m.ibge_code})"


def render_estimate(
    estimate: CostEstimate,
    supplier: SupplierLink | None = None,
    catalog: RefreshResult | None = None,
) -> str:
    e = estimate
    lines = [
        f"Custo estimado: {e.cost.display()}",
        f"Energia: {e.energy.display()} kWh",
        f"({LABEL})",
        "",
        f"Escopo da potência: {_SCOPE[e.scope]}",
        "Composição da taxa:",
        f"  tarifa base: {_rate(e.tarifa_base)}",
        f"  adicional: {_rate(e.adicional)}"
        + (f" (tipo: {e.adicional_tipo})" if e.adicional_tipo else ""),
        f"  taxa total: {_rate(e.taxa_total)}",
    ]
    if e.inclusoes_declaradas:
        lines.append("Inclusões declaradas na tarifa: " + ", ".join(e.inclusoes_declaradas))
    lines += [
        f"Duração solicitada: {_span(e.requested_duration)}",
        f"Duração coberta: {_span(e.coverage_duration)} (cobertura)",
        f"Duração excluída: {_span(e.excluded_duration)}",
    ]
    if e.partial_data:
        lines.append("Dados parciais: o custo cobre apenas a parte coberta.")
        for item in e.excluded_intervals:
            reason = _EXCLUSION.get(item.reason, item.reason)
            lines.append(f"  excluído: {_when(item.start)} a {_when(item.end)} ({reason})")
    if supplier is not None:
        lines.append(render_supplier(supplier))
    for prov in e.provenance:
        lines.append(
            f"Fonte da tarifa: REH {prov.reh}, vigência {_day(prov.inicio)} a {_day(prov.fim)}, "
            f"unidade {prov.units}, gerado em {_day(prov.data_geracao)}"
        )
        lines.append(f"  {prov.source.url} (recurso {prov.source.resource_id})")
        lines.append(f"  Aviso: {prov.warning}")
    if catalog is not None:
        lines.extend(render_catalog(catalog))
    for code in e.warnings:
        lines.append(f"Aviso: {_WARNINGS.get(code, code)} [{code}]")
    return "\n".join(lines) + "\n"


def render_error(code: str, message: str, candidates: tuple[SupplierLink, ...] = ()) -> str:
    lines = [f"Erro [{code}]: {message}"]
    for link in candidates:
        lines.append(f"  candidata: {link.distributor.sig_agente} (CNPJ {link.distributor.cnpj})")
    return "\n".join(lines) + "\n"


# -- sessões ---------------------------------------------------------------------------------

_END_REASON = {
    "user_stop": "encerrada pelo usuário",
    "suspend": "suspensão do sistema",
    "reboot_detected": "reinício detectado",
    "crash_recovered": "queda recuperada",
    "clock_discontinuity": "descontinuidade do relógio",
}

_BASIS = {
    "measured_counter": "medida (contador de energia)",
    "measured_power": "medida (potência instantânea)",
    "user_power": "potência informada",
    "scenario": "cenário (potência nominal)",
}


def _kwh(value: Decimal) -> str:
    return f"{value:.3f}".replace(".", ",")


def _secs(value: Decimal) -> str:
    return _span(timedelta(seconds=int(value)))


def render_tick(view: Any, zone: Any) -> str:
    """Uma linha de acompanhamento (sem quebra de linha)."""
    at = view.at.astimezone(zone).strftime("%H:%M:%S")
    cost = view.cost.display() if view.cost is not None else "indisponível"
    line = (
        f"[{at}] sessão {view.session_id} | medida {_kwh(view.measured_kwh)} kWh"
        f" | assumida {_kwh(view.assumed_kwh)} kWh | custo estimado {cost}"
    )
    if view.stale_for_s is not None:
        line += f" | sem leitura (obsoleta há {int(view.stale_for_s)} s)"
    return line


def render_track_end(result: Any, zone: Any) -> str:
    s, a = result.session, result.acc
    ended = s.ended_at.astimezone(zone).strftime("%d/%m/%Y %H:%M:%S") if s.ended_at else "?"
    lines = [
        f"Sessão {s.id} encerrada em {ended} ({_END_REASON[result.end_reason.value]}).",
        f"Tempo coberto: {_secs(a.covered_s)}; excluído: {_secs(a.excluded_s)}",
    ]
    if a.partial_data:
        lines.append("Dados parciais: há intervalos sem leitura válida.")
    for old, decision in result.recovered:
        reason = _END_REASON[decision.end_reason.value] if decision.end_reason else "?"
        lines.append(f"Sessão anterior {old.id} recuperada: {reason}.")
    lines.extend(f"Aviso: {w}" for w in result.warnings)
    lines.append(f"({LABEL})")
    return "\n".join(lines) + "\n"


def render_session_list(rows: Any, zone: Any) -> str:
    if not rows:
        return "Nenhuma sessão registrada.\n"
    lines = []
    for r in rows:
        s, a = r.session, r.acc
        start = s.started_at.astimezone(zone).strftime("%d/%m/%Y %H:%M:%S")
        end = (
            s.ended_at.astimezone(zone).strftime("%d/%m/%Y %H:%M:%S") if s.ended_at
            else "em andamento"
        )
        reason = s.end_reason.value if s.end_reason else "-"
        lines.append(
            f"Sessão {s.id}: {start} a {end} ({reason}); medida {_kwh(a.measured_wh / 1000)} kWh,"
            f" assumida {_kwh(a.assumed_wh / 1000)} kWh; base: {_BASIS[s.energy_basis.value]};"
            f" escopo: {_SCOPE[s.scope]}" + ("; dados parciais" if a.partial_data else "")
        )
    return "\n".join(lines) + "\n"


def render_period_cost(cost: Any) -> str:
    lines = [
        f"Custo estimado do período: {cost.total_cost.display()}",
        f"  parte medida: {cost.measured_cost.display()} ({_kwh(cost.measured_kwh)} kWh)",
        f"  parte assumida: {cost.assumed_cost.display()} ({_kwh(cost.assumed_kwh)} kWh)",
        f"({LABEL})",
        "",
        f"Sessões consideradas: {cost.sessions}",
        f"Tempo coberto: {_secs(cost.covered_s)}; excluído: {_secs(cost.excluded_s)}",
    ]
    if cost.partial_data:
        lines.append("Dados parciais: o custo cobre apenas a parte coberta.")
    return "\n".join(lines) + "\n"


def render_export(text: str, outcome: Any) -> str:
    out = text.rstrip("\n") + "\n"
    if outcome.truncated:
        out += "Aviso: texto truncado para caber no limite.\n"
    return out
