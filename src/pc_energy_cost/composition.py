"""Composição: único módulo que liga todas as camadas (store, fetcher, cache, providers, casos de uso)."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .application.ports import CatalogFiles
from .application.refresh_catalog import RefreshRequest, RefreshResult, refresh_catalog
from .domain.metering.ports import MeteringProvider
from .domain.shared.errors import InvalidInput
from .infrastructure.aneel.catalog_adapters import AneelCatalogFiles, AneelCatalogParser
from .infrastructure.aneel.ckan import Fetch
from .infrastructure.cache.file_cache import FileCache
from .infrastructure.http.fetcher import download as http_download
from .infrastructure.http.fetcher import fetch_bytes
from .infrastructure.metering.csv_series import CsvPowerSeries
from .infrastructure.metering.linux_rapl import (
    DEFAULT_P_MAX_W,
    DEFAULT_ROOT,
    LinuxRaplProvider,
    SamplingRaplMeter,
)
from .infrastructure.metering.windows_wmi import WindowsWmiProvider
from .infrastructure.persistence.sqlite_store import SqliteStore
from .interface.cli.main import Services

DB_ENV_VAR = "PC_ENERGY_COST_DB"
APP_DIR = "pc-energy-cost"
DB_NAME = "store.sqlite"


def default_db_path(
    env: Mapping[str, str], platform: str | None = None, home: Path | None = None
) -> Path:
    """Diretório de dados do usuário da plataforma (stdlib/pathlib), nunca dentro do repositório."""
    platform = platform or sys.platform
    home = home or Path.home()
    if platform == "win32":
        base = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local")
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(env.get("XDG_DATA_HOME") or home / ".local" / "share")
    return base / APP_DIR / DB_NAME


def resolve_db_path(db_path: Path | None, env: Mapping[str, str]) -> Path:
    """Argumento > variável de ambiente `PC_ENERGY_COST_DB` > padrão da plataforma."""
    if db_path is not None:
        return Path(db_path)
    if env.get(DB_ENV_VAR):
        return Path(env[DB_ENV_VAR])
    return default_db_path(env)


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class _LazyStore:
    """Abre o SQLite só no primeiro uso: `--help` e tarifa manual não criam arquivos."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._store: SqliteStore | None = None

    def _open(self) -> SqliteStore:
        if self._store is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._store = SqliteStore(self._path)
        return self._store

    def __getattr__(self, name: str) -> Any:
        return getattr(self._open(), name)


def _rapl_watts(value: Decimal | None) -> int:
    if value is None:
        return DEFAULT_P_MAX_W
    if value != value.to_integral_value():
        raise InvalidInput("--rapl-max-watts deve ser inteiro entre 1 e 10000")
    return int(value)


def build_services(
    db_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    *,
    fetch_json: Fetch | None = None,
    download: Callable[..., Any] | None = None,
    clock: Any = None,
    platform: str | None = None,
    rapl_root: Path = DEFAULT_ROOT,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    wall_clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Services:
    """Monta adaptadores e casos de uso. Os parâmetros `fetch_json`/`download`/relógios/`rapl_*`
    existem para injetar fontes fake nos testes; o padrão é rede, relógios e sysfs reais."""
    env = env if env is not None else {}
    platform = platform or sys.platform
    clock = clock or _SystemClock()
    path = resolve_db_path(db_path, env)
    store = _LazyStore(path)
    cache_root = path.with_name(path.name + ".cache")
    cache = FileCache(cache_root, now=lambda: clock.now().astimezone(timezone.utc))
    files: CatalogFiles = AneelCatalogFiles(
        cache, fetch_json or fetch_bytes, download or http_download
    )
    parser = AneelCatalogParser()

    def refresh(request: RefreshRequest) -> RefreshResult:
        return refresh_catalog(request, files, parser, store)  # type: ignore[arg-type]

    def meter(rapl_max_watts: Decimal | None) -> MeteringProvider:
        if platform == "win32":
            return WindowsWmiProvider()
        kwargs: dict[str, Any] = {"monotonic_ns": monotonic_ns, "max_watts": _rapl_watts(rapl_max_watts)}
        if wall_clock is not None:
            kwargs["wall_clock"] = wall_clock
        return SamplingRaplMeter(LinuxRaplProvider(rapl_root, **kwargs), sleep=sleep)

    return Services(
        tariff_source=store,  # type: ignore[arg-type]
        clock=clock,
        supplier_source=store,  # type: ignore[arg-type]
        store=store,  # type: ignore[arg-type]
        chooser=None,
        refresh=refresh,
        series_provider=lambda csv_path: CsvPowerSeries(csv_path),
        meter_provider=meter,
    )
