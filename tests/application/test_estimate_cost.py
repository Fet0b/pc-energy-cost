"""Casos de uso de tarifa e estimativa (etapa 7): A19, A29-A33 e casos não numerados."""

import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pc_energy_cost.application.estimate_cost import EstimateRequest, estimate_cost
from pc_energy_cost.application.resolve_tariff import TariffRequest
from pc_energy_cost.domain.metering.model import ExcludedInterval, Sample, SampleUnit, Scope
from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.domain.tariff_catalog.model import SourceInfo, TariffRecord

SP = ZoneInfo("America/Sao_Paulo")
FIXTURE = Path(__file__).parent.parent / "fixtures" / "aneel" / "tarifas_eletropaulo.csv"
CNPJ = "61695227000193"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=SP)
SOURCE = SourceInfo(
    url="https://dadosabertos.aneel.gov.br/api/3/action/package_show?id=tarifas-distribuidoras-energia-eletrica",
    resource_id="fcf2906c-7c32-4b9b-a637-054e7a5234f4",
    metadata_modified="2026-10-18T00:00:00",
    last_modified="Sun, 18 Oct 2026 12:00:00 GMT",
    fetched_at=datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc),
    sha256="0" * 64,
)


def _dec(text: str) -> Decimal:
    return Decimal(text.replace(".", "").replace(",", ".")) if text else Decimal(0)


class FakeTariffSource:
    def __init__(self) -> None:
        with FIXTURE.open(encoding="utf-8", newline="") as fh:
            self.records = [
                TariffRecord(
                    data_geracao=date.fromisoformat(r["DatGeracaoConjuntoDados"]),
                    reh=r["DscREH"], sig_agente=r["SigAgente"], cnpj=r["NumCNPJDistribuidora"],
                    inicio=date.fromisoformat(r["DatInicioVigencia"]),
                    fim=date.fromisoformat(r["DatFimVigencia"]),
                    base=r["DscBaseTarifaria"], subgrupo=r["DscSubGrupo"],
                    modalidade=r["DscModalidadeTarifaria"], classe=r["DscClasse"],
                    subclasse=r["DscSubClasse"], detalhe=r["DscDetalhe"],
                    posto=r["NomPostoTarifario"], unidade=r["DscUnidadeTerciaria"],
                    agente_acessante=r["SigAgenteAcessante"],
                    tusd=_dec(r["VlrTUSD"]), te=_dec(r["VlrTE"]),
                )
                for r in csv.DictReader(fh, delimiter=";")
            ]

    def tariff_records(self, cnpj):
        return [r for r in self.records if r.cnpj == cnpj]

    def source_info(self):
        return SOURCE


class FakeClock:
    def now(self):
        return NOW


def _run(request: EstimateRequest):
    return estimate_cost(request, FakeTariffSource(), FakeClock())


def _manual(total="0,80", **kw):
    return TariffRequest(manual_total=total, **kw)


def _code(exc: pytest.ExceptionInfo) -> str:
    assert isinstance(exc.value, DomainError)
    return exc.value.code


def test_a19_out_of_effect_and_projection():
    request = EstimateRequest(
        tariff=TariffRequest(cnpj=CNPJ), potencia="1000", horas="1",
        inicio=datetime(2027, 7, 4, 10, 0, tzinfo=SP),
    )
    with pytest.raises(DomainError) as exc:
        _run(request)
    assert _code(exc) == "tariff_not_in_effect"
    projected = _run(EstimateRequest(
        tariff=TariffRequest(cnpj=CNPJ, projetar_ultima_tarifa=True), potencia="1000", horas="1",
        inicio=datetime(2027, 7, 4, 10, 0, tzinfo=SP),
    ))
    assert projected.tarifa_base == Decimal("0.78938")
    assert "projected_tariff" in projected.warnings
    assert projected.cost.display() == "R$ 0,79"


def test_a29_manual_all_in_with_declared_inclusions():
    est = _run(EstimateRequest(
        tariff=_manual(inclui=("tributos", "bandeira")), potencia="100", horas="10",
    ))
    assert est.energy.display() == "1,000"
    assert est.cost.display() == "R$ 0,80"
    assert est.inclusoes_declaradas == ("tributos", "bandeira")
    assert est.tarifa_base == Decimal("0.80") and est.adicional == 0
    assert est.taxa_total == Decimal("0.80")


def test_a30_double_inclusion():
    with pytest.raises(DomainError) as exc:
        _run(EstimateRequest(
            tariff=_manual(inclui=("bandeira",), adicional_kwh="0,05", adicional_tipo="bandeira"),
            potencia="100", horas="10",
        ))
    assert _code(exc) == "double_inclusion"
    assert exc.value.exit_code == 2


def test_a31_inclusion_undeclared():
    with pytest.raises(DomainError) as exc:
        _run(EstimateRequest(
            tariff=_manual(adicional_kwh="0,05", adicional_tipo="outro"),
            potencia="100", horas="10",
        ))
    assert _code(exc) == "inclusion_undeclared"
    assert exc.value.exit_code == 2


def test_a32_aneel_plus_additional():
    est = _run(EstimateRequest(
        tariff=TariffRequest(cnpj=CNPJ, adicional_kwh="0,05", adicional_tipo="bandeira"),
        potencia="100", horas="10",
    ))
    assert est.taxa_total == Decimal("0.83938")
    assert est.cost.display() == "R$ 0,84"
    assert "base_excludes_taxes_and_flags" in est.warnings
    assert est.provenance and est.provenance[0].warning == "sem tributos, bandeiras e encargos fixos"
    assert est.inclusoes_declaradas == ()


@pytest.mark.parametrize(
    "value,outcome",
    [("0", "zero"), ("-0,10", "invalid_input"), ("100,000001", "invalid_input"),
     ("0,1234567", "invalid_input"), ("100", "ok")],
)
def test_a33_manual_rate_zero_negative_and_limits(value, outcome):
    request = EstimateRequest(tariff=_manual(value, inclui=("tributos",)), potencia="100", horas="10")
    if outcome == "invalid_input":
        with pytest.raises(DomainError) as exc:
            _run(request)
        assert _code(exc) == "invalid_input"
        return
    est = _run(request)
    if outcome == "zero":
        assert est.cost.display() == "R$ 0,00"
        assert "zero_rate" in est.warnings
    else:
        assert est.cost.display() == "R$ 100,00"
        assert "zero_rate" not in est.warnings


def test_nominal_scenario_is_labelled_scenario():
    est = _run(EstimateRequest(
        tariff=_manual(inclui=("tributos",)), cenario_potencia_nominal="500", horas="2",
    ))
    assert est.scope is Scope.SCENARIO
    assert est.energy.display() == "1,000"


def test_additional_type_without_additional_value_is_invalid():
    with pytest.raises(DomainError) as exc:
        _run(EstimateRequest(tariff=_manual(adicional_tipo="bandeira"), potencia="100", horas="1"))
    assert _code(exc) == "invalid_input"
    with pytest.raises(DomainError) as exc:
        _run(EstimateRequest(tariff=_manual(adicional_kwh="0,05"), potencia="100", horas="1"))
    assert _code(exc) == "invalid_input"
    with pytest.raises(DomainError) as exc:
        _run(EstimateRequest(
            tariff=_manual(inclui=("nao-declarado", "tributos")), potencia="100", horas="1"
        ))
    assert _code(exc) == "invalid_input"


def test_partial_coverage_propagates_from_integration():
    t0 = datetime(2026, 10, 19, 0, 0, tzinfo=SP)
    samples = tuple(
        Sample(t0 + timedelta(minutes=m), Decimal(100), SampleUnit.WATTS) for m in (0, 5, 30, 35)
    )
    est = _run(EstimateRequest(
        tariff=_manual(inclui=("tributos",)), samples=samples, max_gap="5m",
        inicio=t0, fim=t0 + timedelta(minutes=40),
    ))
    assert est.partial_data is True
    assert est.coverage_duration == timedelta(minutes=15)
    assert est.excluded_duration == timedelta(minutes=25)
    assert "partial_data" in est.warnings
    assert est.scope is Scope.MANUAL


def test_pre_excluded_intervals_reach_integration():
    t0 = datetime(2026, 10, 19, 0, 0, tzinfo=SP)
    samples = tuple(
        Sample(t0 + timedelta(minutes=m), Decimal(100), SampleUnit.WATTS) for m in (0, 5, 10)
    )
    pre = (ExcludedInterval(t0 + timedelta(minutes=5), t0 + timedelta(minutes=10), "counter_reset_or_invalid"),)
    est = _run(EstimateRequest(
        tariff=_manual(inclui=("tributos",)), samples=samples, max_gap="5m",
        inicio=t0, fim=t0 + timedelta(minutes=10), pre_excluded=pre,
    ))
    assert est.partial_data is True
    assert est.coverage_duration == timedelta(minutes=5)
    assert est.excluded_duration == timedelta(minutes=5)
    assert any(i.reason == "counter_reset_or_invalid" for i in est.excluded_intervals)


def test_exactly_one_power_source_required():
    with pytest.raises(DomainError) as exc:
        _run(EstimateRequest(tariff=_manual(inclui=("tributos",)), horas="1"))
    assert _code(exc) == "invalid_input"


def test_counter_coverage_source_gives_exit_6_and_csv_default_exit_2():
    from pc_energy_cost.domain.shared.errors import InsufficientCoverage

    samples = (
        Sample(datetime(2026, 10, 19, 10, tzinfo=SP), Decimal(50), SampleUnit.WATTS),
        Sample(datetime(2026, 10, 19, 10, 0, 5, tzinfo=SP), Decimal(50), SampleUnit.WATTS),
    )
    window = dict(inicio=datetime(2026, 10, 19, 12, tzinfo=SP), fim=datetime(2026, 10, 19, 13, tzinfo=SP))
    tariff = TariffRequest(cnpj=CNPJ)
    for source, code in (("csv", 2), ("counter", 6)):
        request = EstimateRequest(tariff=tariff, samples=samples, coverage_source=source, **window)
        with pytest.raises(InsufficientCoverage) as exc:
            estimate_cost(request, FakeTariffSource(), type("C", (), {"now": lambda s: NOW})())
        assert exc.value.exit_code == code
