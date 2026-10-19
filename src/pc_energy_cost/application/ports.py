"""Portas da camada de aplicação (assinaturas mínimas)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from ..domain.location_supplier.model import CoverageIndex, SupplierLink
from ..domain.tariff_catalog.model import SourceInfo, TariffRecord


class TariffSource(Protocol):
    def tariff_records(self, cnpj: str) -> Sequence[TariffRecord]: ...

    def source_info(self) -> SourceInfo: ...


class SupplierSource(Protocol):
    def official_links(self, ibge_code: str) -> Sequence[SupplierLink]: ...

    def user_link(self, ibge_code: str) -> SupplierLink | None: ...


class Clock(Protocol):
    def now(self) -> datetime:
        """Instante atual com fuso."""
        ...


class Store(Protocol):
    def get_preference(self, key: str) -> str | None: ...

    def set_preference(self, key: str, value: str) -> None: ...

    def save_user_link(self, link: SupplierLink) -> None: ...


@dataclass(frozen=True)
class CatalogFile:
    """Arquivo do catálogo no cache local, com a proveniência do download."""

    key: str
    path: Path
    sha256: str
    stored_at: datetime
    url: str
    resource_id: str
    metadata_modified: str
    last_modified: str


class CatalogFiles(Protocol):
    """CKAN + download + cache atômico (a composição liga ckan.py, fetcher.py e file_cache.py)."""

    def cached(self, key: str) -> CatalogFile | None:
        """Entrada do cache ou None; hash divergente ⇒ `cache_corrupted`."""
        ...

    def age(self, key: str) -> timedelta | None:
        """Idade da entrada do cache ou None se ausente; hash divergente ⇒ `cache_corrupted`."""
        ...

    def fetch(self, key: str) -> CatalogFile:
        """Baixa, valida (schema guard) e promove ao cache; falha preserva o cache anterior."""
        ...


class CatalogParser(Protocol):
    def tariffs(self, path: Path) -> Iterator[TariffRecord]: ...

    def coverage(self, indqual: Path, limite: Path) -> CoverageIndex: ...


class CatalogStore(Protocol):
    def load_tariffs(self, records: Iterable[TariffRecord], source: SourceInfo) -> int: ...

    def load_coverage(self, index: CoverageIndex) -> None: ...

    def tariff_vigencia(self) -> tuple[date, date] | None:
        """Menor início e maior fim de vigência do catálogo carregado."""
        ...

    def get_preference(self, key: str) -> str | None: ...

    def set_preference(self, key: str, value: str) -> None: ...


class SupplierChooser(Protocol):
    """Escolha interativa (só em TTY e sem --json); None ⇒ o usuário não escolheu."""

    def choose(self, candidates: Sequence[SupplierLink]) -> SupplierLink | None: ...
