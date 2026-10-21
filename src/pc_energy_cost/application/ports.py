"""Portas da camada de aplicação (assinaturas mínimas)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from ..domain.location_supplier.model import CoverageIndex, SupplierLink
from ..domain.metering.model import Available, ExcludedInterval, Scope, Unavailable
from ..domain.shared.errors import InvalidInput
from ..domain.tariff_catalog.model import SourceInfo, TariffRecord
from ..domain.usage_session.lifecycle import RecoveryDecision
from ..domain.usage_session.model import (
    Accumulator,
    EndReason,
    EnergyBasis,
    ExportOutcome,
    Session,
    SessionCostSummary,
)


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


@dataclass(frozen=True)
class LiveReading:
    """Resultado do último par de leituras: energia e duração, ou um intervalo excluído."""

    energy_wh: Decimal = Decimal(0)
    duration_s: Decimal = Decimal(0)
    excluded: ExcludedInterval | None = None
    assumed: bool = False

    def __post_init__(self) -> None:
        if self.energy_wh < 0 or self.duration_s < 0:
            raise InvalidInput("leitura ao vivo com energia ou duração negativa")
        if self.excluded is not None and self.energy_wh != 0:
            raise InvalidInput("leitura ao vivo: intervalo excluído não carrega energia")


class LiveMeter(Protocol):
    """Leitura incremental do sensor; memória O(1) (só a leitura anterior)."""

    def availability(self) -> Available | Unavailable: ...

    def max_tick_s(self) -> Decimal:
        """Maior intervalo entre leituras sem perder validade."""
        ...

    def energy_basis(self) -> EnergyBasis:
        """Base de energia que as leituras deste medidor representam (contador ou potência)."""
        ...

    def tick(self) -> LiveReading: ...


class SessionLedger(Protocol):
    def open_session(
        self, *, started_at: datetime, boot_id: str | None, sample_interval_s: int,
        persist_interval_s: int, scope: Scope, energy_basis: EnergyBasis,
    ) -> Session: ...

    def heartbeat(self, session_id: int, last_seen_utc: datetime, acc: Accumulator) -> None:
        """Um único UPDATE com o último batimento e os acumuladores."""
        ...

    def close(
        self, session_id: int, ended_at: datetime, end_reason: EndReason, acc: Accumulator
    ) -> Session: ...

    def recover_open(
        self, decide: Callable[[Session], RecoveryDecision]
    ) -> tuple[Session, RecoveryDecision, Accumulator] | None:
        """Numa transação: aplica `decide` à sessão aberta e fecha-a se não estiver viva."""
        ...

    def list_sessions(self, since: datetime | None = None, until: datetime | None = None
                      ) -> Sequence[tuple[Session, Accumulator]]: ...

    def get(self, session_id: int) -> tuple[Session, Accumulator] | None: ...


class SummaryExporter(Protocol):
    def export(self, summary: SessionCostSummary) -> ExportOutcome: ...


class BootIdentity(Protocol):
    def current(self) -> str | None: ...


class MonotonicClock(Protocol):
    def monotonic_ns(self) -> int: ...
