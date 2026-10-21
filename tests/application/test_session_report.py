"""session_report e export_summary com ledger e exportador em memória (S7, S11 parte de aplicação)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from session_fakes import T0, FakeExporter, FakeLedger

from pc_energy_cost.application.export_summary import export_summary
from pc_energy_cost.application.resolve_tariff import TariffRequest
from pc_energy_cost.application.session_report import COST_LABEL, list_sessions, period_cost
from pc_energy_cost.domain.metering.model import Scope
from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.domain.usage_session.model import (
    Accumulator,
    EndReason,
    EnergyBasis,
    Session,
)

TARIFF = TariffRequest(manual_total="0,80", inclui=("tributos",))


def _closed(sid: int, start: datetime, hours: int, basis=EnergyBasis.MEASURED_COUNTER) -> Session:
    end = start + timedelta(hours=hours)
    return Session(sid, start, end, end, EndReason.USER_STOP, "b", 5, 60, Scope.CPU_PACKAGE, basis)


def _ledger() -> FakeLedger:
    ledger = FakeLedger()
    ledger.seed(_closed(1, T0, 2), Accumulator(measured_wh=Decimal(1000), covered_s=Decimal(7200)))
    ledger.seed(
        _closed(2, T0 + timedelta(hours=3), 1, EnergyBasis.USER_POWER),
        Accumulator(assumed_wh=Decimal(500), covered_s=Decimal(3600)),
    )
    return ledger


def test_listar_devolve_sessoes_com_acumuladores():
    rows = list_sessions(_ledger())
    assert [r.session.id for r in rows] == [1, 2]
    assert rows[0].acc.measured_wh == 1000


def test_custo_do_periodo_mostra_partes_e_soma_so_das_partes_visiveis():
    report = period_cost(_ledger(), TARIFF, None, T0 - timedelta(days=1), T0 + timedelta(days=1))
    assert report.measured_kwh == Decimal(1) and report.assumed_kwh == Decimal("0.5")
    assert report.measured_cost.rounded() == Decimal("0.80")
    assert report.assumed_cost.rounded() == Decimal("0.40")
    assert report.total_cost.rounded() == Decimal("1.20")
    assert report.label == COST_LABEL and "não fatura" in COST_LABEL
    assert report.slices  # fatias por vigência


def test_custo_do_periodo_recorta_proporcionalmente_ao_periodo():
    report = period_cost(_ledger(), TARIFF, None, T0, T0 + timedelta(hours=1))
    assert report.measured_kwh == Decimal("0.5")  # metade da sessão 1 (energia sem resolução no tempo)
    assert report.assumed_kwh == 0


def test_custo_do_periodo_exige_inicio_antes_do_fim():
    with pytest.raises(DomainError) as e:
        period_cost(_ledger(), TARIFF, None, T0, T0)
    assert e.value.code == "invalid_interval"


def test_exportar_monta_resumo_e_chama_a_porta():
    exporter = FakeExporter()
    outcome = export_summary(1, _ledger(), exporter, TARIFF, None)
    assert outcome.delivered
    s = exporter.received[0]
    assert s.session_id == 1 and s.measured_energy_kwh == 1 and s.assumed_energy_kwh == 0
    assert s.slices and s.slices[0].measured_energy_kwh == 1


def test_exportar_sem_tarifa_nao_traz_fatias():
    exporter = FakeExporter()
    export_summary(2, _ledger(), exporter, None, None)
    assert exporter.received[0].slices == () and exporter.received[0].assumed_energy_kwh == Decimal("0.5")


def test_exportar_sessao_inexistente_e_session_not_found():
    with pytest.raises(DomainError) as e:
        export_summary(99, _ledger(), FakeExporter(), None, None)
    assert e.value.code == "session_not_found" and e.value.exit_code == 2
