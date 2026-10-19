"""Cliente CKAN: escolha de recurso sobre respostas package_show reais (sem rede)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.infrastructure.aneel.ckan import package_show, resolve_resource

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "aneel"
BASE = "https://dadosabertos.aneel.gov.br/dataset"

TARIFAS_ID = "fcf2906c-7c32-4b9b-a637-054e7a5234f4"
INDQUAL_ID = "3f841488-80a8-42f2-a6ca-e0c593b228de"
DECFEC_ID = "fd69e1dd-fd66-4269-b60c-cc0b7eb221b4"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"package_show_{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("name", "resource_id", "dataset", "pkg_modified", "res_modified", "filename"),
    [
        ("tarifas", TARIFAS_ID, "5a583f3e-1646-4f67-bf0f-69db4203e89e",
         "2026-10-18T10:06:25.956494", "2026-10-18T10:04:31.666080",
         "tarifas-homologadas-distribuidoras-energia-eletrica.csv"),
        ("indqual", INDQUAL_ID, "db9c9f60-b3b5-4504-9dfe-2637922d53ce",
         "2026-09-09T11:06:16.956228", "2026-09-09T11:06:16.949635",
         "indqual-municipio.csv"),
        ("decfec", DECFEC_ID, "d5f0712e-62f6-4736-8dff-9991f10758a7",
         "2026-10-05T05:24:28.800514", "2026-10-05T05:21:14.532917",
         "indicadores-continuidade-coletivos-limite.csv"),
    ],
)
def test_resolve_by_id_in_each_real_package(
    name, resource_id, dataset, pkg_modified, res_modified, filename
):
    ref = resolve_resource(_load(name), resource_id)
    assert ref.resource_id == resource_id
    assert ref.url == f"{BASE}/{dataset}/resource/{resource_id}/download/{filename}"
    assert ref.metadata_modified == pkg_modified
    assert ref.resource_metadata_modified == res_modified


def test_unknown_id_without_fallback_is_error():
    with pytest.raises(DomainError) as exc:
        resolve_resource(_load("tarifas"), "00000000-0000-0000-0000-000000000000")
    assert exc.value.code == "schema_mismatch"


def test_fallback_with_single_candidate_works():
    ref = resolve_resource(
        _load("tarifas"), "00000000-0000-0000-0000-000000000000",
        fallback_name_contains="tarifas-homologadas",
    )
    assert ref.resource_id == TARIFAS_ID


def test_fallback_with_two_candidates_never_chooses():
    pkg = _load("tarifas")
    clone = dict(next(r for r in pkg["result"]["resources"] if r["id"] == TARIFAS_ID))
    clone["id"] = "11111111-1111-1111-1111-111111111111"
    pkg["result"]["resources"].append(clone)
    with pytest.raises(DomainError) as exc:
        resolve_resource(pkg, "00000000-0000-0000-0000-000000000000",
                         fallback_name_contains="tarifas-homologadas")
    assert exc.value.code == "schema_mismatch"


def test_missing_result_key_is_schema_mismatch():
    with pytest.raises(DomainError) as exc:
        resolve_resource({"success": True}, TARIFAS_ID)
    assert exc.value.code == "schema_mismatch"


def test_package_show_uses_injected_fetch():
    seen: list[str] = []
    raw = (FIXTURES / "package_show_indqual.json").read_bytes()

    def fetch(url: str) -> bytes:
        seen.append(url)
        return raw

    data = package_show(fetch, "indqual-municipio")
    assert seen == [
        "https://dadosabertos.aneel.gov.br/api/3/action/package_show?id=indqual-municipio"
    ]
    assert resolve_resource(data, INDQUAL_ID).resource_id == INDQUAL_ID


def test_package_show_invalid_json_is_schema_mismatch():
    with pytest.raises(DomainError) as exc:
        package_show(lambda url: b"<html>", "x")
    assert exc.value.code == "schema_mismatch"
