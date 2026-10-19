"""Contrato TariffSource: o mesmo comportamento no fake em memória e no SqliteStore."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pc_energy_cost.application.ports import TariffSource
from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.domain.tariff_catalog.model import SourceInfo, TariffRecord
from pc_energy_cost.infrastructure.aneel.tariff_csv import read_tariffs
from pc_energy_cost.infrastructure.persistence.sqlite_store import SqliteStore

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "aneel" / "tarifas_eletropaulo.csv"
SOURCE = SourceInfo(
    url="https://example.invalid/t.csv", resource_id="rid", metadata_modified="2026-10-18",
    last_modified="Sun, 18 Oct 2026 00:00:00 GMT",
    fetched_at=datetime(2026, 10, 19, 12, tzinfo=timezone.utc), sha256="a" * 64,
)
ELETROPAULO = "61695227000193"
CEMIG = "06981180000116"


class InMemoryTariffSource:
    def __init__(self) -> None:
        self._records: list[TariffRecord] = []
        self._source: SourceInfo | None = None

    def load(self, records, source):
        self._records, self._source = list(records), source

    def tariff_records(self, cnpj):
        return tuple(r for r in self._records if r.cnpj == cnpj)

    def source_info(self):
        if self._source is None:
            raise DomainError("unavailable", "catálogo de tarifas não carregado")
        return self._source


class SqliteAdapter:
    def __init__(self, path) -> None:
        self.store = SqliteStore(path)

    def load(self, records, source):
        self.store.load_tariffs(records, source)

    def tariff_records(self, cnpj):
        return self.store.tariff_records(cnpj)

    def source_info(self):
        return self.store.source_info()


@pytest.fixture(params=["memory", "sqlite"])
def adapter(request, tmp_path):
    impl = InMemoryTariffSource() if request.param == "memory" else SqliteAdapter(tmp_path / "t.db")
    yield impl
    if isinstance(impl, SqliteAdapter):
        impl.store.close()


def test_unloaded_source_info_is_unavailable(adapter):
    with pytest.raises(DomainError) as exc:
        adapter.source_info()
    assert exc.value.code == "unavailable"


def test_loaded_catalog_contract(adapter):
    expected = list(read_tariffs(FIXTURE))
    adapter.load(iter(expected), SOURCE)
    for cnpj in (ELETROPAULO, CEMIG):
        got = adapter.tariff_records(cnpj)
        assert isinstance(got, tuple)
        assert list(got) == [r for r in expected if r.cnpj == cnpj]
        assert got
    assert adapter.tariff_records("00000000000000") == ()
    assert adapter.source_info() == SOURCE


def test_conforms_to_port_shape(adapter):
    source: TariffSource = adapter
    assert callable(source.tariff_records) and callable(source.source_info)
