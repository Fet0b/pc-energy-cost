"""Domínio TariffCatalog (etapa 5): seleção B1, dedupe e vigência (A16-A18 e casos não numerados)."""

import csv
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.domain.tariff_catalog.model import (
    ELETROPAULO,
    NO_TAXES_WARNING,
    ResolvedTariff,
    SourceInfo,
    TariffProfile,
    TariffRecord,
)
from pc_energy_cost.domain.tariff_catalog.selection import (
    list_vigencias,
    resolve_tariff,
    select_tariff,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "aneel" / "tarifas_eletropaulo.csv"
CNPJ = "61695227000193"
OTHER_CNPJ = "06981180000116"

EXPECTED_HEADER = [
    "DatGeracaoConjuntoDados", "DscREH", "SigAgente", "NumCNPJDistribuidora",
    "DatInicioVigencia", "DatFimVigencia", "DscBaseTarifaria", "DscSubGrupo",
    "DscModalidadeTarifaria", "DscClasse", "DscSubClasse", "DscDetalhe",
    "NomPostoTarifario", "DscUnidadeTerciaria", "SigAgenteAcessante", "VlrTUSD", "VlrTE",
]


def _dec(text: str) -> Decimal:
    return Decimal(text.replace(".", "").replace(",", ".")) if text else Decimal(0)


def _record(row: dict[str, str]) -> TariffRecord:
    return TariffRecord(
        data_geracao=date.fromisoformat(row["DatGeracaoConjuntoDados"]),
        reh=row["DscREH"],
        sig_agente=row["SigAgente"],
        cnpj=row["NumCNPJDistribuidora"],
        inicio=date.fromisoformat(row["DatInicioVigencia"]),
        fim=date.fromisoformat(row["DatFimVigencia"]),
        base=row["DscBaseTarifaria"],
        subgrupo=row["DscSubGrupo"],
        modalidade=row["DscModalidadeTarifaria"],
        classe=row["DscClasse"],
        subclasse=row["DscSubClasse"],
        detalhe=row["DscDetalhe"],
        posto=row["NomPostoTarifario"],
        unidade=row["DscUnidadeTerciaria"],
        agente_acessante=row["SigAgenteAcessante"],
        tusd=_dec(row["VlrTUSD"]),
        te=_dec(row["VlrTE"]),
    )


@pytest.fixture(scope="module")
def records() -> list[TariffRecord]:
    with FIXTURE.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        assert reader.fieldnames == EXPECTED_HEADER
        return [_record(r) for r in reader]


@pytest.fixture
def profile() -> TariffProfile:
    return TariffProfile(cnpj=CNPJ)


SOURCE = SourceInfo(
    url="https://dadosabertos.aneel.gov.br/api/3/action/package_show?id=tarifas-distribuidoras-energia-eletrica",
    resource_id="fcf2906c-7c32-4b9b-a637-054e7a5234f4",
    metadata_modified="2026-10-18T00:00:00",
    last_modified="Sun, 18 Oct 2026 12:00:00 GMT",
    fetched_at=datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc),
    sha256="0" * 64,
)


def _code(exc: pytest.ExceptionInfo) -> str:
    assert isinstance(exc.value, DomainError)
    return exc.value.code


def test_a16_real_b1_selection(records, profile):
    day = date(2026, 10, 19)
    matching = [r for r in set(records) if profile.matches(r) and r.inicio <= day <= r.fim]
    assert len(matching) == 1  # 1 registro após dedupe
    resolved = resolve_tariff(records, profile, day, SOURCE)
    assert resolved.rate.value == Decimal("0.78938")
    assert resolved.record.tusd == Decimal("472.42")
    assert resolved.record.te == Decimal("316.96")
    prov = resolved.provenance
    assert prov.source == SOURCE
    assert prov.reh == "RESOLUÇÃO HOMOLOGATÓRIA Nº 3.596, DE 3 DE JULHO DE 2026"
    assert (prov.inicio, prov.fim) == (date(2026, 7, 4), date(2027, 7, 3))
    assert prov.data_geracao == date(2026, 10, 18)
    assert prov.units == "MWh"
    assert prov.warning == NO_TAXES_WARNING == "sem tributos, bandeiras e encargos fixos"
    assert dict(prov.criteria)["DscSubGrupo"] == "B1"
    assert dict(prov.criteria)["DscBaseTarifaria"] == "Tarifa de Aplicação"
    assert dict(prov.criteria)["NumCNPJDistribuidora"] == CNPJ
    assert ELETROPAULO.cnpj == CNPJ and ELETROPAULO.sig_agente == "ELETROPAULO"
    assert "Eletropaulo Eletricidade de São Paulo S.A" in ELETROPAULO.aliases
    assert "Enel São Paulo" not in ELETROPAULO.aliases


def test_a17_dedupe_vs_ambiguity(records, profile):
    day = date(2026, 10, 19)
    target = select_tariff(records, profile, day)
    # duas linhas totalmente idênticas => usa 1
    assert select_tariff([target, target], profile, day) == target
    # duas com TE diferente => tariff_ambiguous
    other = replace(target, te=target.te + Decimal("1"))
    with pytest.raises(DomainError) as exc:
        select_tariff([target, other], profile, day)
    assert _code(exc) == "tariff_ambiguous"


def test_a18_kw_rows_ignored(records, profile):
    day = date(2026, 10, 19)
    real_kw = [r for r in records if r.unidade == "kW"]
    assert real_kw  # linha real em kW existe no fixture
    target = select_tariff(records, profile, day)
    kw_same_profile = replace(target, unidade="kW", tusd=Decimal("9.89"), te=Decimal(0))
    assert select_tariff([target, kw_same_profile], profile, day) == target
    with pytest.raises(DomainError) as exc:
        select_tariff([kw_same_profile], profile, day)
    assert _code(exc) == "tariff_not_found"


def test_not_found_vs_not_in_effect(records, profile):
    with pytest.raises(DomainError) as exc:
        select_tariff(records, TariffProfile(cnpj=OTHER_CNPJ, subgrupo="A4"), date(2026, 10, 19))
    assert _code(exc) == "tariff_not_found"
    assert exc.value.exit_code == 4
    with pytest.raises(DomainError) as exc:
        select_tariff(records, TariffProfile(cnpj="00000000000000"), date(2026, 10, 19))
    assert _code(exc) == "tariff_not_found"
    # o perfil existe para o CNPJ, mas nenhuma vigência cobre a data
    with pytest.raises(DomainError) as exc:
        select_tariff(records, TariffProfile(cnpj=OTHER_CNPJ), date(2026, 10, 19))
    assert _code(exc) == "tariff_not_in_effect"
    with pytest.raises(DomainError) as exc:
        select_tariff(records, profile, date(2025, 7, 3))
    assert _code(exc) == "tariff_not_in_effect"


def test_validity_boundaries_are_inclusive(records, profile):
    before = select_tariff(records, profile, date(2026, 7, 3))
    after = select_tariff(records, profile, date(2026, 7, 4))
    assert (before.tusd + before.te) / 1000 == Decimal("0.72518")
    assert (after.tusd + after.te) / 1000 == Decimal("0.78938")
    assert select_tariff(records, profile, date(2027, 7, 3)) == after
    assert select_tariff(records, profile, date(2026, 1, 1)) == before
    assert select_tariff(records, profile, date(2025, 12, 31)) == select_tariff(
        records, profile, date(2025, 7, 4)
    )


def test_excluded_variants_baixa_renda_scee_base_economica(records, profile):
    day = date(2026, 10, 19)
    in_effect = [r for r in records if r.inicio <= day <= r.fim and r.cnpj == CNPJ]
    assert {r.subclasse for r in in_effect} >= {"Residencial", "Baixa Renda"}
    assert {r.detalhe for r in in_effect} >= {"Não se aplica", "SCEE"}
    assert {r.base for r in in_effect} >= {"Tarifa de Aplicação", "Base Econômica"}
    selected = select_tariff(records, profile, day)
    assert (selected.subclasse, selected.detalhe, selected.base) == (
        "Residencial", "Não se aplica", "Tarifa de Aplicação",
    )
    # Base Econômica só via perfil explícito
    econ = select_tariff(records, replace(profile, base="Base Econômica"), day)
    assert econ.base == "Base Econômica" and econ.tusd == Decimal("453.32")
    for variant in (
        replace(selected, subclasse="Baixa Renda"),
        replace(selected, detalhe="SCEE"),
        replace(selected, base="Base Econômica"),
        replace(selected, modalidade="Branca"),
        replace(selected, subgrupo="B2"),
        replace(selected, posto="Fora ponta"),
        replace(selected, agente_acessante="X"),
        replace(selected, classe="Comercial"),
    ):
        assert not profile.matches(variant)


def test_split_period_keeps_two_distinct_records_never_summed(records, profile):
    first = select_tariff(records, profile, date(2025, 12, 31))
    second = select_tariff(records, profile, date(2026, 1, 1))
    assert first != second  # vigências distintas
    assert (first.inicio, first.fim) == (date(2025, 7, 4), date(2025, 12, 31))
    assert (second.inicio, second.fim) == (date(2026, 1, 1), date(2026, 7, 3))
    assert (first.reh, first.tusd, first.te) == (second.reh, second.tusd, second.te)
    assert first.tusd == Decimal("432.44") and first.te == Decimal("292.74")
    vigencias = list_vigencias(records, profile)
    assert [(v.inicio, v.fim) for v in vigencias] == [
        (date(2025, 7, 4), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 7, 3)),
        (date(2026, 7, 4), date(2027, 7, 3)),
    ]
    assert resolve_tariff(records, profile, date(2026, 3, 1), SOURCE).rate.value == Decimal("0.72518")


def test_date_after_last_vigencia_is_not_in_effect(records, profile):
    last_fim = max(v.fim for v in list_vigencias(records, profile))
    assert last_fim == date(2027, 7, 3)
    with pytest.raises(DomainError) as exc:
        select_tariff(records, profile, date(2027, 7, 4))
    assert _code(exc) == "tariff_not_in_effect"
    assert exc.value.exit_code == 4


def test_negative_component_of_the_selected_record_is_rejected_not_zeroed(records, profile):
    chosen = resolve_tariff(records, profile, date(2026, 10, 19), SOURCE).record
    for field in ("tusd", "te"):
        negative = replace(chosen, **{field: Decimal("-0.69")})
        with pytest.raises(DomainError) as exc:
            ResolvedTariff.build(negative, profile, SOURCE)
        assert _code(exc) == "schema_mismatch"
