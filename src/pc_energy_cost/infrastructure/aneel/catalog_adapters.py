"""Adaptadores do catálogo ANEEL: CKAN + fetcher + cache de arquivo (CatalogFiles) e parsers."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from ...application.ports import CatalogFile
from ...domain.location_supplier.model import CoverageIndex
from ...domain.tariff_catalog.model import TariffRecord
from ..cache.file_cache import FileCache, Validator
from ..http.fetcher import DownloadResult
from . import supplier_csv, tariff_csv
from .ckan import Fetch, package_show, resolve_resource
from .supplier_csv import build_coverage_index
from .tariff_csv import read_tariffs


@dataclass(frozen=True)
class _Source:
    package_id: str
    resource_id: str
    fallback_name: str
    validator: Validator


SOURCES: dict[str, _Source] = {
    "tarifas": _Source(
        "tarifas-distribuidoras-energia-eletrica",
        "fcf2906c-7c32-4b9b-a637-054e7a5234f4",
        "tarifas-homologadas",
        tariff_csv.check_header,
    ),
    "indqual": _Source(
        "indqual-municipio",
        "3f841488-80a8-42f2-a6ca-e0c593b228de",
        "indqual-municipio",
        supplier_csv.check_indqual_header,
    ),
    "limite": _Source(
        "indicadores-coletivos-de-continuidade-dec-e-fec",
        "fd69e1dd-fd66-4269-b60c-cc0b7eb221b4",
        "indicadores-continuidade-coletivos-limite",
        supplier_csv.check_limite_header,
    ),
}
_PROV_FIELDS = ("url", "resource_id", "metadata_modified", "last_modified")

Download = Callable[[str, Path], DownloadResult]


class AneelCatalogFiles:
    """Liga ckan.py (resolve o recurso), o download e o file_cache (atômico, schema guard).

    A proveniência (URL, resource id, `metadata_modified`, `Last-Modified`) fica num sidecar
    `<chave>.prov.json`, gravado depois da promoção ao cache; sem sidecar válido, a entrada é
    tratada como ausente (será baixada de novo).
    """

    def __init__(self, cache: FileCache, fetch_json: Fetch, download: Download) -> None:
        self._cache = cache
        self._fetch_json = fetch_json
        self._download = download

    @staticmethod
    def _source(key: str) -> _Source:
        try:
            return SOURCES[key]
        except KeyError:
            raise ValueError(f"fonte de catálogo desconhecida: {key!r}") from None

    def _prov_path(self, key: str) -> Path:
        return self._cache.path_for(key).with_name(key + ".prov.json")

    def cached(self, key: str) -> CatalogFile | None:
        self._source(key)
        entry = self._cache.lookup(key)
        if entry is None:
            return None
        try:
            prov = json.loads(self._prov_path(key).read_text(encoding="utf-8"))
            values = {name: str(prov[name]) for name in _PROV_FIELDS}
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return CatalogFile(key, entry.path, entry.sha256, entry.stored_at, **values)

    def age(self, key: str) -> timedelta | None:
        self._source(key)
        return self._cache.age(key)

    def fetch(self, key: str) -> CatalogFile:
        source = self._source(key)
        package = package_show(self._fetch_json, source.package_id)
        ref = resolve_resource(package, source.resource_id, source.fallback_name)
        part = self._cache.part_path(key)
        downloaded = self._download(ref.url, part)
        stored = self._cache.store(key, part, downloaded.sha256, source.validator)
        prov = {
            "url": ref.url,
            "resource_id": ref.resource_id,
            "metadata_modified": ref.metadata_modified,
            "last_modified": downloaded.last_modified,
        }
        tmp = self._prov_path(key).with_suffix(".json.part")
        tmp.write_text(json.dumps(prov), encoding="utf-8")
        tmp.replace(self._prov_path(key))
        return CatalogFile(key, stored.path, stored.sha256, stored.stored_at, **prov)


class AneelCatalogParser:
    def tariffs(self, path: Path) -> Iterator[TariffRecord]:
        return read_tariffs(path)

    def coverage(self, indqual: Path, limite: Path) -> CoverageIndex:
        return build_coverage_index(indqual, limite)


