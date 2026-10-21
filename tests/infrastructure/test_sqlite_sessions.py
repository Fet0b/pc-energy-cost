"""Ledger SQLite de sessões: arquivo próprio, WAL só nele, recuperação, falha cedo."""

import hashlib
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from pc_energy_cost.application.ports import SessionLedger
from pc_energy_cost.domain.location_supplier.resolver import user_confirmed_link
from pc_energy_cost.domain.location_supplier.model import Municipality
from pc_energy_cost.domain.metering.model import Scope
from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.domain.tariff_catalog.model import ELETROPAULO
from pc_energy_cost.domain.usage_session.lifecycle import RecoveryDecision, decide_recovery
from pc_energy_cost.domain.usage_session.model import Accumulator, EndReason, EnergyBasis
from pc_energy_cost.infrastructure.persistence.sqlite_sessions import (
    LEDGER_SCHEMA_VERSION,
    SqliteSessionLedger,
    sessions_path_for,
)
from pc_energy_cost.infrastructure.persistence.sqlite_store import SqliteStore

T0 = datetime(2026, 10, 21, 12, 0, 0, 123456, tzinfo=timezone.utc)


def _open(ledger, at=T0, boot="boot-1"):
    return ledger.open_session(
        started_at=at, boot_id=boot, sample_interval_s=5, persist_interval_s=60,
        scope=Scope.WHOLE_SYSTEM_AC, energy_basis=EnergyBasis.MEASURED_COUNTER,
    )


@pytest.fixture
def path(tmp_path):
    return tmp_path / "sessions.sqlite"


@pytest.fixture
def ledger(path):
    led = SqliteSessionLedger(path)
    yield led
    led.close_connection()


def test_implements_port_and_own_schema_version(path, ledger):
    port: SessionLedger = ledger
    assert port is ledger
    assert path.exists()
    raw = sqlite3.connect(path)
    try:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == LEDGER_SCHEMA_VERSION == 1
        assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        raw.close()


def test_default_path_is_sibling_of_store(tmp_path):
    from pc_energy_cost.composition import default_db_path
    d = default_db_path({"XDG_DATA_HOME": str(tmp_path)}, platform="linux", home=tmp_path)
    s = sessions_path_for(d)
    assert s.parent == d.parent and s.name == "sessions.sqlite"


def test_decimal_and_datetime_roundtrip(ledger):
    s = _open(ledger)
    assert s.id == 1 and s.is_open and s.started_at == T0 and s.last_seen_utc == T0
    acc = Accumulator(
        measured_wh=Decimal("12.3456789012345678901234567890"),
        assumed_wh=Decimal("0.0000000000000000000001"),
        covered_s=Decimal("123.456789"), excluded_s=Decimal("7.000001"),
        partial_data=True, stale=True,
    )
    seen = T0 + timedelta(seconds=60)
    ledger.heartbeat(s.id, seen, acc)
    got, got_acc = ledger.get(s.id)
    assert got_acc == acc and got.last_seen_utc == seen
    assert got.scope is Scope.WHOLE_SYSTEM_AC and got.energy_basis is EnergyBasis.MEASURED_COUNTER
    assert got.boot_id == "boot-1" and got.sample_interval_s == 5 and got.persist_interval_s == 60
    assert ledger.get(99) is None


def test_close_and_list_filter(ledger):
    a = _open(ledger)
    closed = ledger.close(a.id, T0 + timedelta(hours=1), EndReason.USER_STOP, Accumulator())
    assert not closed.is_open and closed.end_reason is EndReason.USER_STOP
    b = _open(ledger, T0 + timedelta(hours=5))
    assert [s.id for s, _ in ledger.list_sessions()] == [a.id, b.id]
    assert [s.id for s, _ in ledger.list_sessions(since=T0 + timedelta(hours=2))] == [b.id]
    assert [s.id for s, _ in ledger.list_sessions(until=T0 + timedelta(hours=2))] == [a.id]


def test_s9_kill_without_stop_then_recover(path):
    led = SqliteSessionLedger(path)
    s = _open(led)
    seen = T0 + timedelta(seconds=60)
    led.heartbeat(s.id, seen, Accumulator(measured_wh=Decimal("5")))
    led._conn.close()  # "kill": sem stop
    led2 = SqliteSessionLedger(path)
    try:
        later = seen + timedelta(hours=1)
        found = led2.recover_open(lambda x: decide_recovery(x, "boot-1", later))
        assert found is not None
        old, decision, acc = found
        assert old.last_seen_utc == seen and acc.measured_wh == Decimal("5")
        assert not decision.alive and decision.end_reason is EndReason.CRASH_RECOVERED
        got, _ = led2.get(s.id)
        assert got.ended_at == seen and got.end_reason is EndReason.CRASH_RECOVERED
        assert led2.recover_open(lambda x: decide_recovery(x, "boot-1", later)) is None
    finally:
        led2.close_connection()


def test_second_connection_sees_live_session(path, ledger):
    s = _open(ledger)
    other = SqliteSessionLedger(path)
    try:
        now = T0 + timedelta(seconds=30)
        found = other.recover_open(lambda x: decide_recovery(x, "boot-1", now))
        assert found is not None and found[1].alive and found[0].id == s.id
        assert other.get(s.id)[0].is_open  # viva: não alterada
    finally:
        other.close_connection()


def test_recover_none_when_empty(ledger):
    assert ledger.recover_open(lambda s: RecoveryDecision(True)) is None


def test_s9_store_untouched_by_ledger(tmp_path):
    store_path = tmp_path / "store.sqlite"
    store = SqliteStore(store_path)
    store.set_preference("k", "v")
    store.save_user_link(user_confirmed_link(Municipality("3550308", "São Paulo", "SP"), ELETROPAULO))
    store.close()
    raw = sqlite3.connect(store_path)
    mode = raw.execute("PRAGMA journal_mode").fetchone()[0]
    raw.close()
    assert mode != "wal"
    before = hashlib.sha256(store_path.read_bytes()).hexdigest()

    led = SqliteSessionLedger(tmp_path / "sessions.sqlite")
    s = _open(led)
    led.heartbeat(s.id, T0 + timedelta(seconds=60), Accumulator())
    led.close(s.id, T0 + timedelta(seconds=61), EndReason.USER_STOP, Accumulator())
    led.close_connection()

    assert hashlib.sha256(store_path.read_bytes()).hexdigest() == before
    assert not (tmp_path / "store.sqlite-wal").exists()
    assert not (tmp_path / "store.sqlite-shm").exists()
    raw = sqlite3.connect(store_path)
    assert raw.execute("PRAGMA journal_mode").fetchone()[0] == mode
    raw.close()


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="permissão de arquivo não é confiável (Windows ou root)",
)
def test_read_only_database_fails_early(path):
    SqliteSessionLedger(path).close_connection()
    for p in path.parent.glob("sessions.sqlite*"):
        p.chmod(0o444)
    path.parent.chmod(0o555)
    try:
        with pytest.raises(DomainError) as e:
            SqliteSessionLedger(path)
        assert e.value.code == "unavailable" and "sessões" in e.value.message
    finally:
        path.parent.chmod(0o755)
        for p in path.parent.glob("sessions.sqlite*"):
            p.chmod(0o644)


def test_locked_database_fails_early_with_message(path, ledger):
    blocker = sqlite3.connect(path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        other = SqliteSessionLedger(path, busy_timeout_s=0)
        with pytest.raises(DomainError) as e:
            _open(other)
        assert e.value.code == "unavailable" and "bloqueado" in e.value.message
        other.close_connection()
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()


def test_ledger_connection_uses_synchronous_full(ledger):
    # 2 == FULL (https://www.sqlite.org/pragma.html#pragma_synchronous)
    assert ledger._conn.execute("PRAGMA synchronous").fetchone()[0] == 2


def test_late_heartbeat_does_not_overwrite_closed_session(ledger):
    s = _open(ledger)
    seen = T0 + timedelta(seconds=60)
    ledger.heartbeat(s.id, seen, Accumulator(measured_wh=Decimal("5")))
    later = seen + timedelta(hours=1)
    ledger.recover_open(lambda x: decide_recovery(x, "boot-1", later))  # fecha como crash_recovered
    ledger.heartbeat(s.id, later, Accumulator(measured_wh=Decimal("99")))  # batimento tardio
    got, acc = ledger.get(s.id)
    assert got.ended_at == seen and got.end_reason is EndReason.CRASH_RECOVERED
    assert got.last_seen_utc == seen and acc.measured_wh == Decimal("5")


def test_s10_takeover_fences_old_owner_heartbeat_and_close(path, ledger):
    # Dois "processos": `ledger` é o dono antigo (A); `novo` abre a mesma base e assume (B).
    a = _open(ledger)
    ledger.heartbeat(a.id, T0 + timedelta(seconds=60), Accumulator(measured_wh=Decimal("5")))
    novo = SqliteSessionLedger(path)
    try:
        takeover_at = T0 + timedelta(hours=1)
        recovered = novo.recover_open(lambda s: decide_recovery(s, "boot-2", takeover_at))
        assert recovered is not None and recovered[0].end_reason is EndReason.REBOOT_DETECTED
        b = _open(novo, at=takeover_at, boot="boot-2")
        novo.heartbeat(b.id, takeover_at + timedelta(seconds=60), Accumulator(measured_wh=Decimal("7")))
        snapshot = (novo.get(a.id), novo.get(b.id))

        # O dono antigo ainda está vivo e tenta bater e fechar: nada pode mudar nas linhas.
        ledger.heartbeat(a.id, takeover_at + timedelta(seconds=90), Accumulator(measured_wh=Decimal("99")))
        with pytest.raises(DomainError) as err:
            ledger.close(a.id, takeover_at + timedelta(seconds=120), EndReason.USER_STOP,
                         Accumulator(measured_wh=Decimal("99")))
        assert err.value.code == "session_already_open"
        assert (novo.get(a.id), novo.get(b.id)) == snapshot
    finally:
        novo.close_connection()
