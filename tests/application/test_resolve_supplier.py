"""Caso de uso resolve_supplier (etapa 11): D8, persistência separada do oficial."""

from pathlib import Path

import pytest

from pc_energy_cost.application.resolve_supplier import (
    SupplierAmbiguous,
    SupplierRequest,
    resolve_supplier,
)
from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.infrastructure.aneel.supplier_csv import build_coverage_index
from pc_energy_cost.infrastructure.persistence.sqlite_store import SqliteStore

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "aneel"
SP, ERERE = "3550308", "2304277"
ELETROPAULO, CERIS = "61695227000193", None


class Chooser:
    def __init__(self, index: int | None = 0) -> None:
        self.index, self.calls = index, 0

    def choose(self, candidates):
        self.calls += 1
        return None if self.index is None else candidates[self.index]


@pytest.fixture
def store(tmp_path):
    s = SqliteStore(tmp_path / "db.sqlite")
    s.load_coverage(build_coverage_index(FIX / "indqual_capital.csv", FIX / "limite_recorte.csv"))
    yield s
    s.close()


def test_unique_official_resolves_without_asking(store):
    chooser = Chooser()
    link = resolve_supplier(SupplierRequest(ERERE, tty=True), store, store, chooser)
    assert not link.user_confirmed and link.confidence == "official_indicator_join"
    assert chooser.calls == 0 and store.user_link(ERERE) is None


def test_tty_choice_goes_through_port_and_is_persisted_separately(store):
    chooser = Chooser(0)
    link = resolve_supplier(SupplierRequest(SP, tty=True), store, store, chooser)
    assert chooser.calls == 1
    assert link.user_confirmed and link.source == "user"
    saved = store.user_link(SP)
    assert saved is not None and saved.distributor.cnpj == link.distributor.cnpj
    assert not any(l.user_confirmed for l in store.official_links(SP))
    # segunda chamada reutiliza a escolha salva, sem perguntar
    again = resolve_supplier(SupplierRequest(SP, tty=True), store, store, chooser)
    assert again.distributor.cnpj == link.distributor.cnpj and chooser.calls == 1


def test_no_tty_raises_supplier_ambiguous_with_candidates(store):
    chooser = Chooser()
    with pytest.raises(SupplierAmbiguous) as exc:
        resolve_supplier(SupplierRequest(SP, tty=False), store, store, chooser)
    assert exc.value.code == "supplier_ambiguous" and exc.value.exit_code == 3
    assert len(exc.value.candidates) == 2
    assert chooser.calls == 0 and store.user_link(SP) is None


def test_json_never_asks_even_on_tty(store):
    chooser = Chooser()
    with pytest.raises(SupplierAmbiguous):
        resolve_supplier(SupplierRequest(SP, tty=True, json=True), store, store, chooser)
    assert chooser.calls == 0


def test_user_cancelling_chooser_is_ambiguous(store):
    with pytest.raises(SupplierAmbiguous):
        resolve_supplier(SupplierRequest(SP, tty=True), store, store, Chooser(None))
    assert store.user_link(SP) is None


def test_distribuidora_cnpj_resolves_and_persists(store):
    link = resolve_supplier(SupplierRequest(SP, distribuidora="61.695.227/0001-93"), store, store)
    assert link.distributor.cnpj == ELETROPAULO and link.user_confirmed
    assert store.user_link(SP).distributor.cnpj == ELETROPAULO


def test_distribuidora_outside_candidates_is_invalid_input(store):
    with pytest.raises(DomainError) as exc:
        resolve_supplier(SupplierRequest(SP, distribuidora="00000000000000"), store, store)
    assert exc.value.code == "invalid_input"
    assert store.user_link(SP) is None


def test_explicit_distribuidora_overrides_saved_choice(store):
    resolve_supplier(SupplierRequest(SP, tty=True), store, store, Chooser(0))
    other = [l for l in store.official_links(SP) if l.distributor.cnpj != store.user_link(SP).distributor.cnpj][0]
    link = resolve_supplier(SupplierRequest(SP, distribuidora=other.distributor.cnpj), store, store)
    assert link.distributor.cnpj == other.distributor.cnpj
    assert store.user_link(SP).distributor.cnpj == other.distributor.cnpj


def test_unsupported_and_invalid_ibge(store):
    with pytest.raises(DomainError) as exc:
        resolve_supplier(SupplierRequest("1234567"), store, store)
    assert exc.value.code == "unsupported" and exc.value.exit_code == 3
    with pytest.raises(DomainError) as exc:
        resolve_supplier(SupplierRequest("12"), store, store)
    assert exc.value.code == "invalid_input"
