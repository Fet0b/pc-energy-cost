"""Estimativa de custo (etapa 7): A4, A20 e casos não numerados de divisão por vigências."""

import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pc_energy_cost.domain.energy_estimation.estimate import (
    RateExtras,
    RateWindow,
    estimate_average_power,
    split_by_vigencia,
)
from pc_energy_cost.domain.metering.model import Scope
from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.domain.shared.units import UnitRateBRLPerKWh, Watts
from pc_energy_cost.domain.tariff_catalog.model import TariffProfile, TariffRecord
from pc_energy_cost.domain.tariff_catalog.selection import select_tariff

SP = ZoneInfo("America/Sao_Paulo")
FIXTURE = Path(__file__).parent.parent / "fixtures" / "aneel" / "tarifas_eletropaulo.csv"
PROFILE = TariffProfile(cnpj="61695227000193")
NO_EXTRAS = RateExtras(adicional=UnitRateBRLPerKWh(Decimal(0)))


def _dec(text: str) -> Decimal:
    return Decimal(text.replace(".", "").replace(",", ".")) if text else Decimal(0)


def _load() -> list[TariffRecord]:
    with FIXTURE.open(encoding="utf-8", newline="") as fh:
        return [
            TariffRecord(
                data_geracao=date.fromisoformat(r["DatGeracaoConjuntoDados"]),
                reh=r["DscREH"], sig_agente=r["SigAgente"], cnpj=r["NumCNPJDistribuidora"],
                inicio=date.fromisoformat(r["DatInicioVigencia"]),
                fim=date.fromisoformat(r["DatFimVigencia"]),
                base=r["DscBaseTarifaria"], subgrupo=r["DscSubGrupo"],
                modalidade=r["DscModalidadeTarifaria"], classe=r["DscClasse"],
                subclasse=r["DscSubClasse"], detalhe=r["DscDetalhe"], posto=r["NomPostoTarifario"],
                unidade=r["DscUnidadeTerciaria"], agente_acessante=r["SigAgenteAcessante"],
                tusd=_dec(r["VlrTUSD"]), te=_dec(r["VlrTE"]),
            )
            for r in csv.DictReader(fh, delimiter=";")
        ]


@pytest.fixture(scope="module")
def lookup():
    records = _load()

    def _lookup(day: date) -> RateWindow:
        rec = select_tariff(records, PROFILE, day)
        rate = UnitRateBRLPerKWh((rec.tusd + rec.te) / Decimal(1000))
        return RateWindow(rate=rate, last_day=rec.fim)

    return _lookup


def test_a04_zero_physical_is_valid_money_zero(lookup):
    start = datetime(2026, 10, 19, 8, 0, tzinfo=SP)
    zero_watts = estimate_average_power(Watts(Decimal(0)), start, datetime(2026, 10, 19, 13, 0, tzinfo=SP), lookup, NO_EXTRAS)
    zero_hours = estimate_average_power(Watts(Decimal(100)), start, start, lookup, NO_EXTRAS)
    for est in (zero_watts, zero_hours):
        assert est.cost.display() == "R$ 0,00"
        assert est.partial_data is False
        assert est.energy.value == 0


def test_a20_split_by_vigencia_real_records(lookup):
    est = estimate_average_power(
        Watts(Decimal(100)),
        datetime(2026, 7, 3, 12, 0, tzinfo=SP), datetime(2026, 7, 4, 12, 0, tzinfo=SP),
        lookup, NO_EXTRAS,
    )
    assert [s.energy.value for s in est.slices] == [Decimal("1.2"), Decimal("1.2")]
    assert est.cost_unrounded == Decimal("1.2") * Decimal("0.72518") + Decimal("1.2") * Decimal("0.78938")
    assert est.cost_unrounded == Decimal("1.817472")
    assert est.cost.display() == "R$ 1,82"
    # período partido (mesma REH e mesmos valores): duas fatias, registros nunca somados
    split = estimate_average_power(
        Watts(Decimal(100)),
        datetime(2025, 12, 31, 12, 0, tzinfo=SP), datetime(2026, 1, 1, 12, 0, tzinfo=SP),
        lookup, NO_EXTRAS,
    )
    assert [s.energy.value for s in split.slices] == [Decimal("1.2"), Decimal("1.2")]
    assert {s.rate for s in split.slices} == {Decimal("0.72518")}
    assert split.cost_unrounded == Decimal("1.740432")
    assert split.cost.display() == "R$ 1,74"


def test_split_slices_are_contiguous_and_cover_interval(lookup):
    start = datetime(2026, 7, 3, 12, 0, tzinfo=SP)
    end = datetime(2026, 7, 5, 6, 0, tzinfo=SP)
    slices = split_by_vigencia(start, end, lookup, SP)
    assert len(slices) == 2
    assert slices[0].start == start and slices[-1].end == end
    assert slices[0].end == slices[1].start == datetime(2026, 7, 4, 0, 0, tzinfo=SP)


def test_split_without_record_after_last_vigencia_errors(lookup):
    with pytest.raises(DomainError) as exc:
        split_by_vigencia(
            datetime(2027, 7, 3, 12, 0, tzinfo=SP), datetime(2027, 7, 4, 12, 0, tzinfo=SP), lookup, SP
        )
    assert exc.value.code == "tariff_not_in_effect"


def test_additional_is_summed_and_only_cost_is_rounded():
    window = RateWindow(rate=UnitRateBRLPerKWh(Decimal("0.78938")))
    extras = RateExtras(adicional=UnitRateBRLPerKWh(Decimal("0.05")), tipo="bandeira")
    est = estimate_average_power(
        Watts(Decimal(100)),
        datetime(2026, 10, 19, 0, 0, tzinfo=SP), datetime(2026, 10, 19, 10, 0, tzinfo=SP),
        lambda day: window, extras, scope=Scope.SCENARIO,
    )
    assert est.taxa_total == Decimal("0.83938")
    assert est.tarifa_base == Decimal("0.78938") and est.adicional == Decimal("0.05")
    assert est.cost_unrounded == Decimal("0.83938") and est.cost.display() == "R$ 0,84"
    assert est.scope is Scope.SCENARIO
    assert est.requested_duration == est.coverage_duration
