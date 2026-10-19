"""Caso de uso: atualizar o catálogo (CKAN ⇒ download ⇒ cache ⇒ parse único ⇒ store), D7."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ..domain.shared.errors import DomainError
from ..domain.tariff_catalog.model import SourceInfo
from .ports import CatalogFile, CatalogFiles, CatalogParser, CatalogStore

TTL = timedelta(hours=24)
KEY_TARIFFS, KEY_INDQUAL, KEY_LIMITE = "tarifas", "indqual", "limite"
KEYS = (KEY_TARIFFS, KEY_INDQUAL, KEY_LIMITE)
CATALOG_LABEL = "parcial / indicativo"
_PREF_TARIFFS = "catalog_sha256:tarifas"
_PREF_COVERAGE = "catalog_sha256:coverage"


@dataclass(frozen=True)
class RefreshRequest:
    permitir_cache_vencido: bool = False
    force: bool = False


@dataclass(frozen=True)
class RefreshResult:
    refreshed: bool  # houve download
    stale: bool  # dados vencidos usados por falta de rede (exige a flag explícita)
    age: timedelta  # idade da entrada mais antiga do cache
    vigencia: tuple[date, date] | None
    label: str = CATALOG_LABEL
    tariffs_loaded: int | None = None  # None: catálogo de tarifas já estava carregado


def _cache_state(files: CatalogFiles, key: str) -> tuple[CatalogFile | None, timedelta | None]:
    try:
        entry = files.cached(key)
        age = files.age(key) if entry is not None else None
    except DomainError as exc:
        if exc.code == "cache_corrupted":
            return None, None  # recarrega
        raise
    return (entry, age) if entry is not None and age is not None else (None, None)


def _hours(age: timedelta) -> str:
    return f"{age.total_seconds() / 3600:.0f} h"


def refresh_catalog(
    request: RefreshRequest, files: CatalogFiles, parser: CatalogParser, store: CatalogStore
) -> RefreshResult:
    entries: dict[str, CatalogFile] = {}
    ages: dict[str, timedelta] = {}
    refreshed = stale = False
    # baixa tudo antes de gravar no store: falha em qualquer fonte deixa o store anterior intacto
    for key in KEYS:
        entry, age = _cache_state(files, key)
        if entry is not None and age is not None and age < TTL and not request.force:
            entries[key], ages[key] = entry, age
            continue
        try:
            entries[key] = files.fetch(key)
            ages[key] = files.age(key) or timedelta(0)
            refreshed = True
        except DomainError as exc:
            if exc.code != "network_unavailable":
                raise
            if entry is None or age is None:
                raise DomainError(
                    "network_unavailable", f"{exc.message}; sem cache local de '{key}'"
                ) from exc
            if not request.permitir_cache_vencido:
                raise DomainError(
                    "network_unavailable",
                    f"sem rede e cache de '{key}' vencido (idade {_hours(age)}); "
                    "use --permitir-cache-vencido para usá-lo",
                ) from exc
            entries[key], ages[key] = entry, age
            stale = True

    coverage_sha = f"{entries[KEY_INDQUAL].sha256}:{entries[KEY_LIMITE].sha256}"
    if store.get_preference(_PREF_COVERAGE) != coverage_sha:
        index = parser.coverage(entries[KEY_INDQUAL].path, entries[KEY_LIMITE].path)
        store.load_coverage(index)
        store.set_preference(_PREF_COVERAGE, coverage_sha)

    loaded: int | None = None
    tariffs = entries[KEY_TARIFFS]
    if store.get_preference(_PREF_TARIFFS) != tariffs.sha256:
        source = SourceInfo(
            url=tariffs.url,
            resource_id=tariffs.resource_id,
            metadata_modified=tariffs.metadata_modified,
            last_modified=tariffs.last_modified,
            fetched_at=tariffs.stored_at,
            sha256=tariffs.sha256,
        )
        loaded = store.load_tariffs(parser.tariffs(tariffs.path), source)
        store.set_preference(_PREF_TARIFFS, tariffs.sha256)

    return RefreshResult(
        refreshed=refreshed,
        stale=stale,
        age=max(ages.values()),
        vigencia=store.tariff_vigencia(),
        tariffs_loaded=loaded,
    )
