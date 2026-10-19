"""Domínio LocationSupplierMapping (etapa 6): A24-A27 e casos não numerados."""

import csv
from collections import defaultdict
from pathlib import Path

import pytest

from pc_energy_cost.domain.location_supplier.model import (
    AgentLimit,
    Ambiguous,
    CoverageIndex,
    Municipality,
    Resolved,
    Unsupported,
)
from pc_energy_cost.domain.location_supplier.resolver import (
    resolve_supplier,
    user_confirmed_link,
)
from pc_energy_cost.domain.tariff_catalog.model import ELETROPAULO

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "aneel"
SP = "3550308"
ELETROPAULO_CNPJ = "61695227000193"
CERIS_CNPJ = "57384943000182"
EPB_CNPJ = "09095183000140"
EBO_CNPJ = "08826596000195"


def _read(name: str, encoding: str) -> list[dict[str, str]]:
    with open(FIXTURES / name, encoding=encoding, newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def _load_index() -> CoverageIndex:
    municipalities: dict[str, Municipality] = {}
    conjuntos: dict[str, list[str]] = defaultdict(list)
    for row in _read("indqual_capital.csv", "cp1252"):
        code = row["CodMunicipio"]
        municipalities[code] = Municipality(code, row["NomMunicipio"], row["SigUF"])
        conjuntos[code].append(row["IdeConjUnidConsumidoras"])
    agents: dict[str, list[AgentLimit]] = defaultdict(list)
    for row in _read("limite_recorte.csv", "utf-8-sig"):
        agents[row["IdeConjUndConsumidoras"]].append(
            AgentLimit(row["NumCNPJ"], row["SigAgente"], int(row["AnoLimiteQualidade"]))
        )
    return CoverageIndex(
        municipalities,
        {k: tuple(v) for k, v in conjuntos.items()},
        {k: tuple(v) for k, v in agents.items()},
    )


@pytest.fixture(scope="module")
def index() -> CoverageIndex:
    return _load_index()


def test_a24_mapeamento_capital_ambiguo(index):
    result = resolve_supplier(SP, index)
    assert isinstance(result, Ambiguous)
    counts = {c.distributor.cnpj: c.evidence["n_conjuntos"] for c in result.candidates}
    assert counts == {ELETROPAULO_CNPJ: 199, CERIS_CNPJ: 1}
    names = {c.distributor.cnpj: c.distributor.sig_agente for c in result.candidates}
    assert names == {ELETROPAULO_CNPJ: "ELETROPAULO", CERIS_CNPJ: "CERIS"}
    for cand in result.candidates:
        assert cand.evidence["conjuntos_sem_agente"] == ("12450",)
        assert cand.source == "aneel:indqual+dec-fec"
        assert cand.confidence == "official_indicator_join"
        assert cand.user_confirmed is False
        assert cand.municipality.ibge_code == SP


def test_a25_sucessao_historica(index):
    mun = index.municipalities["2504009"]
    only_6818 = CoverageIndex(
        {mun.ibge_code: mun}, {mun.ibge_code: ("6818",)}, {"6818": index.agents["6818"]}
    )
    assert {a.cnpj for a in only_6818.agents["6818"]} == {EBO_CNPJ, EPB_CNPJ}
    assert {a.year for a in only_6818.agents["6818"] if a.cnpj == EBO_CNPJ} == set(range(2000, 2011))
    assert {a.year for a in only_6818.agents["6818"] if a.cnpj == EPB_CNPJ} == set(range(2010, 2014))
    result = resolve_supplier("2504009", only_6818)
    assert isinstance(result, Resolved)
    link = result.link
    assert link.distributor.cnpj == EPB_CNPJ  # a chave é o CNPJ; EBO (2000-2010) descartado
    assert link.distributor.sig_agente == "EPB"  # sem espaços à direita
    assert link.evidence["ano_limite_usado"] == (2013,)
    assert link.evidence["n_conjuntos"] == 1
    assert link.evidence["conjuntos_sem_agente"] == ()


def test_a26_municipio_agente_unico(index):
    result = resolve_supplier("2304277", index)
    assert isinstance(result, Resolved)
    assert result.link.municipality.name == "Ererê"
    assert result.link.evidence["n_conjuntos"] == 2
    assert result.link.confidence == "official_indicator_join"


def test_a27_cobertura_ausente(index):
    result = resolve_supplier("9999999", index)
    assert isinstance(result, Unsupported)
    assert result.ibge_code == "9999999"


def test_empate_de_cnpjs_no_mesmo_ano_ambos_candidatos():
    mun = Municipality("1234567", "Teste", "XX")
    idx = CoverageIndex(
        {"1234567": mun},
        {"1234567": ("1",)},
        {"1": (
            AgentLimit("11111111000111", "AAA   ", 2020),
            AgentLimit("22222222000122", "BBB   ", 2020),
            AgentLimit("33333333000133", "OLD   ", 2010),
        )},
    )
    result = resolve_supplier("1234567", idx)
    assert isinstance(result, Ambiguous)
    assert {c.distributor.cnpj for c in result.candidates} == {"11111111000111", "22222222000122"}
    assert {c.distributor.sig_agente for c in result.candidates} == {"AAA", "BBB"}
    assert all(c.evidence["n_conjuntos"] == 1 for c in result.candidates)


def test_municipio_sem_nenhum_agente_e_unsupported():
    mun = Municipality("1234567", "Teste", "XX")
    idx = CoverageIndex({"1234567": mun}, {"1234567": ("9",)}, {})
    assert isinstance(resolve_supplier("1234567", idx), Unsupported)


def test_vinculo_do_usuario_separado_do_oficial(index):
    official = resolve_supplier(SP, index)
    assert isinstance(official, Ambiguous)
    mun = index.municipalities[SP]
    user = user_confirmed_link(mun, ELETROPAULO)
    assert user.source == "user"
    assert user.user_confirmed is True
    assert user.distributor == ELETROPAULO
    assert all(c.user_confirmed is False and c.source != "user" for c in official.candidates)
    again = resolve_supplier(SP, index)  # o resultado oficial não muda com o vínculo do usuário
    assert again == official
