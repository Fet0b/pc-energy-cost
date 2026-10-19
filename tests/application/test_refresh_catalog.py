"""Caso de uso refresh_catalog (etapa 11): A23 e casos não numerados, com fakes das portas."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from pc_energy_cost.application.ports import CatalogFile
from pc_energy_cost.application.refresh_catalog import (
    CATALOG_LABEL,
    KEYS,
    RefreshRequest,
    refresh_catalog,
)
from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.infrastructure.aneel.supplier_csv import build_coverage_index
from pc_energy_cost.infrastructure.aneel.tariff_csv import read_tariffs

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "aneel"
PATHS = {
    "tarifas": FIX / "tarifas_eletropaulo.csv",
    "indqual": FIX / "indqual_capital.csv",
    "limite": FIX / "limite_recorte.csv",
}
T0 = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


class FakeFiles:
    def __init__(self) -> None:
        self.entries: dict[str, CatalogFile] = {}
        self.ages: dict[str, timedelta] = {}
        self.fetch_calls: list[str] = []
        self.failures: dict[str, DomainError] = {}
        self.corrupted: set[str] = set()
        self.downloads = 0

    def cached(self, key):
        if key in self.corrupted:
            raise DomainError("cache_corrupted", "hash")
        return self.entries.get(key)

    def age(self, key):
        if key in self.corrupted:
            raise DomainError("cache_corrupted", "hash")
        return self.ages.get(key)

    def fetch(self, key):
        self.fetch_calls.append(key)
        if key in self.failures:
            raise self.failures[key]
        self.corrupted.discard(key)
        self.downloads += 1
        n = self.downloads
        self.entries[key] = CatalogFile(
            key=key, path=PATHS[key], sha256=f"{n:064d}", stored_at=T0,
            url=f"https://example.invalid/{key}.csv", resource_id=f"rid-{key}",
            metadata_modified="2026-10-18", last_modified="Sun, 18 Oct 2026 00:00:00 GMT",
        )
        self.ages[key] = timedelta(0)
        return self.entries[key]

    def set_age(self, hours: float) -> None:
        for key in self.entries:
            self.ages[key] = timedelta(hours=hours)


class FakeParser:
    def __init__(self) -> None:
        self.tariff_parses = 0
        self.fail_coverage: DomainError | None = None

    def tariffs(self, path):
        self.tariff_parses += 1
        return read_tariffs(path)

    def coverage(self, indqual, limite):
        if self.fail_coverage:
            raise self.fail_coverage
        return build_coverage_index(indqual, limite)


class FakeStore:
    def __init__(self) -> None:
        self.tariff_loads = 0
        self.coverage_loads = 0
        self.records: list = []
        self.sources: list = []
        self.prefs: dict[str, str] = {}

    def load_tariffs(self, records, source):
        loaded = list(records)  # parse com falha deixa a carga anterior intacta
        self.records, self.tariff_loads = loaded, self.tariff_loads + 1
        self.sources.append(source)
        return len(loaded)

    def load_coverage(self, index):
        self.coverage_loads += 1

    def tariff_vigencia(self):
        if not self.records:
            return None
        return min(r.inicio for r in self.records), max(r.fim for r in self.records)

    def get_preference(self, key):
        return self.prefs.get(key)

    def set_preference(self, key, value):
        self.prefs[key] = value


@pytest.fixture
def env():
    return FakeFiles(), FakeParser(), FakeStore()


def test_first_refresh_downloads_parses_once_and_labels_partial(env):
    files, parser, store = env
    result = refresh_catalog(RefreshRequest(), files, parser, store)
    assert files.fetch_calls == list(KEYS)
    assert parser.tariff_parses == 1
    assert store.tariff_loads == 1 and store.coverage_loads == 1
    assert result.refreshed and not result.stale
    assert result.label == CATALOG_LABEL == "parcial / indicativo"
    assert result.tariffs_loaded == len(store.records) > 0
    assert result.vigencia == (date(2025, 7, 4), date(2027, 7, 3))
    source = store.sources[0]
    assert source.resource_id == "rid-tarifas" and source.fetched_at == T0


def test_refresh_within_ttl_does_not_download_again(env):
    files, parser, store = env
    refresh_catalog(RefreshRequest(), files, parser, store)
    files.set_age(23)
    result = refresh_catalog(RefreshRequest(), files, parser, store)
    assert files.fetch_calls == list(KEYS)  # nenhuma chamada nova
    assert parser.tariff_parses == 1 and store.tariff_loads == 1
    assert not result.refreshed and not result.stale
    assert result.age == timedelta(hours=23)
    assert result.vigencia == (date(2025, 7, 4), date(2027, 7, 3))


def test_a23_offline_with_30h_cache_needs_flag_and_reports_stale_age(env):
    files, parser, store = env
    refresh_catalog(RefreshRequest(), files, parser, store)
    files.set_age(30)
    files.fetch_calls.clear()
    down = DomainError("network_unavailable", "sem rede")
    files.failures = {k: down for k in KEYS}

    with pytest.raises(DomainError) as exc:
        refresh_catalog(RefreshRequest(), files, parser, store)
    assert exc.value.code == "network_unavailable"
    assert "30" in exc.value.message  # idade do cache

    result = refresh_catalog(RefreshRequest(permitir_cache_vencido=True), files, parser, store)
    assert result.stale is True and not result.refreshed
    assert result.age == timedelta(hours=30)
    assert result.vigencia == (date(2025, 7, 4), date(2027, 7, 3))
    assert store.tariff_loads == 1  # dados do cache já carregados, nada fabricado


def test_offline_without_any_cache_fails_even_with_flag(env):
    files, parser, store = env
    files.failures = {k: DomainError("network_unavailable", "sem rede") for k in KEYS}
    with pytest.raises(DomainError) as exc:
        refresh_catalog(RefreshRequest(permitir_cache_vencido=True), files, parser, store)
    assert exc.value.code == "network_unavailable"
    assert store.tariff_loads == 0


def test_failure_midway_keeps_previous_cache_and_store(env):
    files, parser, store = env
    refresh_catalog(RefreshRequest(), files, parser, store)
    previous = {k: files.entries[k].sha256 for k in KEYS}
    files.set_age(30)
    files.failures = {"indqual": DomainError("download_incomplete", "cortou")}
    with pytest.raises(DomainError) as exc:
        refresh_catalog(RefreshRequest(), files, parser, store)
    assert exc.value.code == "download_incomplete"
    assert store.tariff_loads == 1 and store.coverage_loads == 1
    assert files.entries["indqual"].sha256 == previous["indqual"]


def test_parse_failure_does_not_mark_loaded_and_retry_heals(env):
    files, parser, store = env
    parser.fail_coverage = DomainError("schema_mismatch", "coluna")
    with pytest.raises(DomainError):
        refresh_catalog(RefreshRequest(), files, parser, store)
    parser.fail_coverage = None
    files.set_age(1)
    files.fetch_calls.clear()
    result = refresh_catalog(RefreshRequest(), files, parser, store)
    assert files.fetch_calls == []  # cache dentro do TTL é reaproveitado
    assert store.coverage_loads == 1 and result.refreshed is False


def test_corrupted_cache_is_reloaded(env):
    files, parser, store = env
    refresh_catalog(RefreshRequest(), files, parser, store)
    files.corrupted.add("tarifas")
    files.fetch_calls.clear()
    refresh_catalog(RefreshRequest(), files, parser, store)
    assert files.fetch_calls == ["tarifas"]
    assert store.tariff_loads == 2
