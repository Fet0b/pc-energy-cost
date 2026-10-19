"""Adaptadores do catálogo (CKAN + fetcher + cache + parsers + store) com fontes FAKE, sem rede."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pc_energy_cost.application.refresh_catalog import RefreshRequest, refresh_catalog
from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.infrastructure.aneel.catalog_adapters import (
    AneelCatalogFiles,
    AneelCatalogParser,
)
from pc_energy_cost.infrastructure.cache.file_cache import FileCache
from pc_energy_cost.infrastructure.http.fetcher import DownloadResult
from pc_energy_cost.infrastructure.persistence.sqlite_store import SqliteStore

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "aneel"
LAST_MODIFIED = "Sun, 18 Oct 2026 12:00:00 GMT"
T0 = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
# arquivo da fixture por sufixo da URL do recurso real (nada é baixado)
FILES = {
    "tarifas-homologadas-distribuidoras-energia-eletrica.csv": "tarifas_eletropaulo.csv",
    "indqual-municipio.csv": "indqual_capital.csv",
    "indicadores-continuidade-coletivos-limite.csv": "limite_recorte.csv",
}
PACKAGES = {
    "tarifas-distribuidoras-energia-eletrica": "package_show_tarifas.json",
    "indqual-municipio": "package_show_indqual.json",
    "indicadores-coletivos-de-continuidade-dec-e-fec": "package_show_decfec.json",
}


class FakeNet:
    def __init__(self) -> None:
        self.json_urls: list[str] = []
        self.downloads: list[str] = []
        self.offline = False

    def fetch_json(self, url: str) -> bytes:
        self.json_urls.append(url)
        if self.offline:
            raise DomainError("network_unavailable", "offline (fake)")
        package = url.split("id=")[1]
        return (FIX / PACKAGES[package]).read_bytes()

    def download(self, url: str, part: Path) -> DownloadResult:
        self.downloads.append(url)
        if self.offline:
            raise DomainError("network_unavailable", "offline (fake)")
        source = FIX / FILES[url.rsplit("/", 1)[1]]
        part.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, part)
        data = part.read_bytes()
        return DownloadResult(part, hashlib.sha256(data).hexdigest(), len(data), LAST_MODIFIED)


@pytest.fixture
def clock():
    return [T0]


@pytest.fixture
def net():
    return FakeNet()


@pytest.fixture
def files(tmp_path, clock, net):
    cache = FileCache(tmp_path / "cache", now=lambda: clock[0])
    return AneelCatalogFiles(cache, net.fetch_json, net.download)


def test_fetch_supplies_full_provenance_including_last_modified(files, net):
    entry = files.fetch("tarifas")
    assert entry.resource_id == "fcf2906c-7c32-4b9b-a637-054e7a5234f4"
    assert entry.url.endswith("tarifas-homologadas-distribuidoras-energia-eletrica.csv")
    assert entry.last_modified == LAST_MODIFIED
    assert entry.metadata_modified
    assert entry.sha256 == hashlib.sha256((FIX / "tarifas_eletropaulo.csv").read_bytes()).hexdigest()
    assert entry.stored_at == T0 and entry.path.exists()
    assert net.json_urls[0].endswith("id=tarifas-distribuidoras-energia-eletrica")


def test_cached_and_age_roundtrip_keep_provenance(files, clock):
    assert files.cached("indqual") is None and files.age("indqual") is None
    fetched = files.fetch("indqual")
    clock[0] = T0 + timedelta(hours=3)
    assert files.cached("indqual") == fetched
    assert files.age("indqual") == timedelta(hours=3)


def test_cached_without_provenance_sidecar_is_a_miss(files, tmp_path):
    files.fetch("limite")
    (tmp_path / "cache" / "limite.prov.json").unlink()
    assert files.cached("limite") is None


def test_corrupted_cache_is_reported(files, tmp_path):
    files.fetch("tarifas")
    (tmp_path / "cache" / "tarifas").write_bytes(b"adulterado")
    with pytest.raises(DomainError) as exc:
        files.cached("tarifas")
    assert exc.value.code == "cache_corrupted"


def test_schema_guard_runs_and_bad_header_never_reaches_cache(tmp_path, clock, net):
    def bad_download(url, part):
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b'"X";"Y"\n"1";"2"\n')
        return DownloadResult(part, hashlib.sha256(part.read_bytes()).hexdigest(), 16, "")

    cache = FileCache(tmp_path / "cache", now=lambda: clock[0])
    files = AneelCatalogFiles(cache, net.fetch_json, bad_download)
    with pytest.raises(DomainError) as exc:
        files.fetch("tarifas")
    assert exc.value.code == "schema_mismatch"
    assert files.cached("tarifas") is None


def test_unknown_key_is_rejected(files):
    with pytest.raises(ValueError):
        files.fetch("outro")


def test_refresh_catalog_with_real_adapters_loads_sqlite_store_and_is_idempotent(
    files, net, tmp_path
):
    store = SqliteStore(tmp_path / "db.sqlite")
    parser = AneelCatalogParser()
    first = refresh_catalog(RefreshRequest(), files, parser, store)
    assert first.refreshed and first.tariffs_loaded and first.vigencia is not None
    assert store.tariff_records("61695227000193")
    assert store.source_info().last_modified == LAST_MODIFIED
    assert store.official_links("3550308")
    downloads = len(net.downloads)
    second = refresh_catalog(RefreshRequest(), files, parser, store)
    assert not second.refreshed and second.tariffs_loaded is None
    assert len(net.downloads) == downloads  # cache fresco: sem novo download
    store.close()


def test_offline_with_expired_cache_needs_explicit_flag(files, net, clock, tmp_path):
    store = SqliteStore(tmp_path / "db.sqlite")
    parser = AneelCatalogParser()
    refresh_catalog(RefreshRequest(), files, parser, store)
    clock[0] = T0 + timedelta(hours=30)
    net.offline = True
    with pytest.raises(DomainError) as exc:
        refresh_catalog(RefreshRequest(), files, parser, store)
    assert exc.value.code == "network_unavailable"
    result = refresh_catalog(RefreshRequest(permitir_cache_vencido=True), files, parser, store)
    assert result.stale and result.age >= timedelta(hours=30)
    store.close()


def test_provenance_sidecar_is_valid_json(files, tmp_path):
    files.fetch("tarifas")
    data = json.loads((tmp_path / "cache" / "tarifas.prov.json").read_text(encoding="utf-8"))
    assert set(data) == {"url", "resource_id", "metadata_modified", "last_modified"}
