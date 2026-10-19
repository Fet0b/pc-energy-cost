"""Store SQLite (etapa 10): A28, migração, consulta, rollback."""

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from pc_energy_cost.application.ports import Store, SupplierSource, TariffSource
from pc_energy_cost.domain.location_supplier.model import Ambiguous, Municipality
from pc_energy_cost.domain.location_supplier.resolver import (
    resolve_supplier,
    user_confirmed_link,
)
from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.domain.tariff_catalog.model import ELETROPAULO, SourceInfo
from pc_energy_cost.infrastructure.aneel.supplier_csv import build_coverage_index
from pc_energy_cost.infrastructure.aneel.tariff_csv import read_tariffs
from pc_energy_cost.infrastructure.persistence.sqlite_store import (
    SCHEMA_VERSION,
    SqliteStore,
)

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "aneel"
SP = "3550308"


def _source(sha: str = "a" * 64) -> SourceInfo:
    return SourceInfo(
        url="https://example.invalid/t.csv",
        resource_id="rid",
        metadata_modified="2026-10-18",
        last_modified="Sun, 18 Oct 2026 00:00:00 GMT",
        fetched_at=datetime(2026, 10, 19, 12, tzinfo=timezone.utc),
        sha256=sha,
    )


@pytest.fixture
def store(tmp_path):
    s = SqliteStore(tmp_path / "db.sqlite")
    yield s
    s.close()


def test_a28_user_choice_is_persisted_separately_from_official(tmp_path, store):
    store.load_coverage(build_coverage_index(FIX / "indqual_capital.csv", FIX / "limite_recorte.csv"))
    official = store.official_links(SP)
    assert len(official) == 2 and not any(l.user_confirmed for l in official)
    assert store.user_link(SP) is None
    muni = Municipality(SP, "São Paulo", "SP")
    store.save_user_link(user_confirmed_link(muni, ELETROPAULO))
    store.close()

    reopened = SqliteStore(tmp_path / "db.sqlite")
    try:
        user = reopened.user_link(SP)
        assert user is not None and user.user_confirmed
        assert user.confidence == "user_confirmed" and user.source == "user"
        assert user.distributor.cnpj == ELETROPAULO.cnpj
        assert user.municipality == muni
        again = reopened.official_links(SP)
        assert [l.distributor.cnpj for l in again] == [l.distributor.cnpj for l in official]
        assert all(l.confidence == "official_indicator_join" for l in again)
    finally:
        reopened.close()


def test_official_links_match_resolver_with_tuple_evidence(store):
    index = build_coverage_index(FIX / "indqual_capital.csv", FIX / "limite_recorte.csv")
    store.load_coverage(index)
    expected = resolve_supplier(SP, index)
    assert isinstance(expected, Ambiguous)
    assert tuple(store.official_links(SP)) == expected.candidates
    assert store.official_links("9999999") == ()


def test_user_link_evidence_roundtrips_as_json(store):
    link = user_confirmed_link(Municipality(SP, "São Paulo", "SP"), ELETROPAULO)
    link = type(link)(
        link.municipality, link.distributor, link.source,
        {"ano_limite_usado": (2024, 2025)}, link.confidence, True,
    )
    store.save_user_link(link)
    assert store.user_link(SP).evidence["ano_limite_usado"] == (2024, 2025)


def test_protocols_are_implemented(store):
    t: TariffSource = store
    s: SupplierSource = store
    st: Store = store
    assert t and s and st


def test_migration_creates_versioned_schema(tmp_path):
    path = tmp_path / "m.sqlite"
    SqliteStore(path).close()
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"tariffs", "user_links", "preferences", "cache_index"} <= names
    assert any("cnpj" in n and "vigencia" in n for n in names)
    conn.close()
    SqliteStore(path).close()  # idempotente


def test_tariff_query_by_cnpj_matches_fixture(store):
    records = list(read_tariffs(FIX / "tarifas_eletropaulo.csv"))
    store.load_tariffs(records, _source())
    for cnpj in {r.cnpj for r in records}:
        assert list(store.tariff_records(cnpj)) == [r for r in records if r.cnpj == cnpj]
    assert store.tariff_records("00000000000000") == ()
    assert store.source_info() == _source()
    got = [r for r in store.tariff_records(ELETROPAULO.cnpj) if r.covers(date(2026, 7, 4))]
    assert got


def test_source_info_without_load_is_unavailable(store):
    with pytest.raises(DomainError) as exc:
        store.source_info()
    assert exc.value.code == "unavailable"


def test_failed_load_rolls_back_and_keeps_previous(store):
    records = list(read_tariffs(FIX / "tarifas_eletropaulo.csv"))
    store.load_tariffs(records, _source("a" * 64))

    def broken():
        yield from records[:5]
        raise DomainError("schema_mismatch", "falha no meio")

    with pytest.raises(DomainError):
        store.load_tariffs(broken(), _source("b" * 64))
    assert store.source_info().sha256 == "a" * 64
    assert list(store.tariff_records(ELETROPAULO.cnpj)) == [
        r for r in records if r.cnpj == ELETROPAULO.cnpj
    ]


def test_failed_coverage_load_rolls_back(store):
    index = build_coverage_index(FIX / "indqual_capital.csv", FIX / "limite_recorte.csv")
    store.load_coverage(index)
    bad = type(index)({SP: None}, index.conjuntos, index.agents)  # type: ignore[arg-type]
    with pytest.raises(Exception):
        store.load_coverage(bad)
    assert len(store.official_links(SP)) == 2


def test_preferences_and_cache_index(store):
    assert store.get_preference("k") is None
    store.set_preference("k", "v1")
    store.set_preference("k", "v2")
    assert store.get_preference("k") == "v2"
    assert store.get_cache_entry("tarifas.csv") is None
    store.set_cache_entry("tarifas.csv", "c" * 64, "2026-10-19T12:00:00+00:00")
    assert store.get_cache_entry("tarifas.csv") == ("c" * 64, "2026-10-19T12:00:00+00:00")


def test_tariff_vigencia_range(store):
    assert store.tariff_vigencia() is None
    store.load_tariffs(read_tariffs(FIX / "tarifas_eletropaulo.csv"), _source())
    assert store.tariff_vigencia() == (date(2025, 7, 4), date(2027, 7, 3))
