"""S11: exportador de texto Proxmox-compatível (sem rede, sem credencial)."""

from datetime import date, datetime, timezone
from decimal import Decimal

from pc_energy_cost.application.ports import SummaryExporter
from pc_energy_cost.domain.metering.model import Scope
from pc_energy_cost.domain.usage_session.model import (
    EnergyBasis,
    SessionCostSummary,
    SummarySlice,
)
from pc_energy_cost.infrastructure.export.proxmox_text import (
    PUBLIC_NAME,
    ProxmoxCompatibleTextExporter,
)

T0 = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 21, 13, 30, tzinfo=timezone.utc)


def _summary(slices=(), partial=False, assumed="0", measured="1.5", ended=T1, **kw):
    return SessionCostSummary(
        session_id=7, started_at=T0, ended_at=ended,
        measured_energy_kwh=Decimal(measured), assumed_energy_kwh=Decimal(assumed),
        covered_s=Decimal(5400), excluded_s=Decimal(0), partial_data=partial,
        scope=kw.get("scope", Scope.CPU_PACKAGE),
        energy_basis=kw.get("basis", EnergyBasis.MEASURED_COUNTER), slices=tuple(slices),
    )


def _slice(day, m="1.5", a="0", rate="0.80"):
    d = date(2026, 10, day)
    return SummarySlice(d, d, Decimal(m), Decimal(a), Decimal(rate))


def test_s11_required_labels_and_name():
    out = ProxmoxCompatibleTextExporter()
    text, truncated = out.render(_summary([_slice(21)]))
    assert not truncated
    assert PUBLIC_NAME == "Proxmox-compatível (texto)"
    assert PUBLIC_NAME in text
    assert "estimativa, não fatura" in text
    assert "cpu_package" in text
    assert "Energia medida: 1,500 kWh" in text
    assert "Energia assumida: 0,000 kWh" in text
    assert "Custo estimado: R$ 1,20" in text
    assert "R$ 0,800000/kWh" in text
    assert "2026-10-21" in text
    assert "dados parciais" not in text.lower()
    assert "oficial" not in text.lower()
    for markup in ("<", "**", "# ", "```"):
        assert markup not in text


def test_s11_partial_data_and_open_session_and_no_tariff():
    text, _ = ProxmoxCompatibleTextExporter().render(_summary(partial=True, ended=None))
    assert "dados parciais" in text.lower()
    assert "em andamento" in text
    assert "Custo estimado: indisponível" in text  # sem tarifa: nunca zero
    assert "estimativa, não fatura" in text


def test_s11_assumed_energy_is_separate():
    s = _summary(slices=[_slice(21, m="0", a="2", rate="0.5")], measured="0", assumed="2",
                 basis=EnergyBasis.USER_POWER, scope=Scope.MANUAL)
    text, _ = ProxmoxCompatibleTextExporter().render(s)
    assert "Energia assumida: 2,000 kWh" in text
    assert "Energia medida: 0,000 kWh" in text
    assert "Custo estimado: R$ 1,00" in text


def test_s11_short_text_within_limits():
    text, truncated = ProxmoxCompatibleTextExporter().render(_summary([_slice(21)]))
    assert not truncated
    assert len(text) <= 8192 and len(text.encode("utf-8")) <= 8192


def test_s11_truncates_by_whole_lines_and_keeps_labels():
    slices = [SummarySlice(date(2026, 1, 1), date(2026, 1, 1), Decimal("0.001"), Decimal(0),
                           Decimal("0.80")) for _ in range(2000)]
    text, truncated = ProxmoxCompatibleTextExporter().render(_summary(slices))
    assert truncated
    assert len(text) <= 8192
    assert len(text.encode("utf-8")) <= 8192
    assert "estimativa, não fatura" in text and "cpu_package" in text
    full_lines = {f"  2026-01-01 a 2026-01-01: R$ 0,800000/kWh; 0,001 kWh; R$ 0,00"}
    body = [ln for ln in text.splitlines() if ln.startswith("  2026-01-01")]
    assert body and all(ln in full_lines for ln in body)  # nenhuma linha cortada ao meio


def test_s11_bytes_limit_is_stricter_than_chars():
    summary = _summary([_slice(21) for _ in range(30)])
    full, _ = ProxmoxCompatibleTextExporter().render(summary)
    assert len(full.encode("utf-8")) > len(full)  # há caracteres de vários bytes
    # limite em caracteres suficiente, mas em bytes insuficiente: ainda assim trunca
    limit = len(full)
    text, truncated = ProxmoxCompatibleTextExporter(limit=limit).render(summary)
    assert truncated
    assert len(text) <= limit and len(text.encode("utf-8")) <= limit
    assert all(ln in full.splitlines() or ln.startswith("[texto truncado")
               for ln in text.splitlines())


def test_s11_export_outcome_returns_text_without_sink():
    exp = ProxmoxCompatibleTextExporter()
    port: SummaryExporter = exp
    outcome = port.export(_summary([_slice(21)]))
    assert outcome.delivered is False and not outcome.truncated
    assert "estimativa, não fatura" in outcome.detail


def test_s11_export_delivers_to_injected_sink():
    got: list[str] = []
    exp = ProxmoxCompatibleTextExporter(sink=got.append, destination="arquivo X")
    outcome = exp.export(_summary([_slice(21)]))
    assert outcome.delivered is True and outcome.detail == "arquivo X"
    assert len(got) == 1 and "estimativa, não fatura" in got[0]


def test_s11_export_outcome_reports_truncation():
    exp = ProxmoxCompatibleTextExporter(limit=300)
    outcome = exp.export(_summary([_slice(21) for _ in range(30)]))
    assert outcome.truncated is True and outcome.delivered is False
    assert len(outcome.detail) <= 300 and "[texto truncado" in outcome.detail
    got: list[str] = []
    out2 = ProxmoxCompatibleTextExporter(sink=got.append, limit=300).export(
        _summary([_slice(21) for _ in range(30)]))
    assert out2.truncated is True and out2.delivered is True and len(got[0]) <= 300
