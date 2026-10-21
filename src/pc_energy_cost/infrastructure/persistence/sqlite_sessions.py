"""Ledger SQLite de sessões de uso, em arquivo PRÓPRIO (`sessions.sqlite`).

Não abre nem migra o `store.sqlite`. Este arquivo usa `journal_mode=WAL` e
`synchronous=FULL` (segundo https://www.sqlite.org/pragma.html, FULL em WAL é durável
em perda de energia). Datas: texto UTC de formato fixo (ordenável). Energia e segundos:
texto Decimal, sem perda.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ...domain.metering.model import Scope
from ...domain.shared.errors import DomainError, UnavailableError
from ...domain.usage_session.lifecycle import RecoveryDecision
from ...domain.usage_session.model import Accumulator, EndReason, EnergyBasis, Session

LEDGER_SCHEMA_VERSION = 1
SESSIONS_DB_NAME = "sessions.sqlite"

_SCHEMA = """
CREATE TABLE usage_sessions (
    id INTEGER PRIMARY KEY,
    started_at_utc TEXT NOT NULL,
    ended_at_utc TEXT,
    last_seen_utc TEXT NOT NULL,
    end_reason TEXT,
    boot_id TEXT,
    sample_interval_s INTEGER NOT NULL,
    persist_interval_s INTEGER NOT NULL,
    scope TEXT NOT NULL,
    energy_basis TEXT NOT NULL,
    measured_wh TEXT NOT NULL DEFAULT '0',
    assumed_wh TEXT NOT NULL DEFAULT '0',
    covered_s TEXT NOT NULL DEFAULT '0',
    excluded_s TEXT NOT NULL DEFAULT '0',
    partial_data INTEGER NOT NULL DEFAULT 0,
    stale INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_usage_sessions_open ON usage_sessions (ended_at_utc);
"""
# covered_s/excluded_s são TEXT Decimal (o acumulador usa Decimal; INTEGER perderia frações).

_COLS = (
    "id, started_at_utc, ended_at_utc, last_seen_utc, end_reason, boot_id, sample_interval_s, "
    "persist_interval_s, scope, energy_basis, measured_wh, assumed_wh, covered_s, excluded_s, "
    "partial_data, stale"
)
_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def sessions_path_for(store_path: Path) -> Path:
    """Irmão do arquivo do store: mesmo diretório de dados, arquivo `sessions.sqlite`."""
    return store_path.with_name(SESSIONS_DB_NAME)


def _ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(_FMT)


def _parse(text: str) -> datetime:
    return datetime.strptime(text, _FMT).replace(tzinfo=timezone.utc)


def _unavailable(exc: sqlite3.Error) -> DomainError:
    msg = str(exc).lower()
    if "locked" in msg or "busy" in msg:
        return UnavailableError(f"banco de sessões bloqueado por outro processo: {exc}")
    return UnavailableError(f"banco de sessões inacessível ou somente leitura: {exc}")


def _row_to_session(r: tuple) -> tuple[Session, Accumulator]:
    session = Session(
        id=r[0], started_at=_parse(r[1]), ended_at=_parse(r[2]) if r[2] else None,
        last_seen_utc=_parse(r[3]), end_reason=EndReason(r[4]) if r[4] else None,
        boot_id=r[5], sample_interval_s=r[6], persist_interval_s=r[7],
        scope=Scope(r[8]), energy_basis=EnergyBasis(r[9]),
    )
    acc = Accumulator(
        measured_wh=Decimal(r[10]), assumed_wh=Decimal(r[11]), covered_s=Decimal(r[12]),
        excluded_s=Decimal(r[13]), partial_data=bool(r[14]), stale=bool(r[15]),
    )
    return session, acc


def _acc_params(acc: Accumulator) -> tuple:
    return (str(acc.measured_wh), str(acc.assumed_wh), str(acc.covered_s), str(acc.excluded_s),
            int(acc.partial_data), int(acc.stale))


class SqliteSessionLedger:
    def __init__(self, path: Path, busy_timeout_s: float = 5.0) -> None:
        self._conn: sqlite3.Connection | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(path, isolation_level=None, timeout=busy_timeout_s)
            self._conn.execute("PRAGMA journal_mode=WAL")  # fora de transação
            self._conn.execute("PRAGMA synchronous=FULL")
            self._migrate()
        except OSError as exc:
            raise UnavailableError(f"banco de sessões inacessível: {exc}") from exc
        except sqlite3.Error as exc:
            self.close_connection()
            raise _unavailable(exc) from exc

    def close_connection(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _migrate(self) -> None:
        assert self._conn is not None
        current = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if current > LEDGER_SCHEMA_VERSION:
            raise UnavailableError("banco de sessões é de uma versão mais nova do programa")
        if current == LEDGER_SCHEMA_VERSION:
            return
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            if self._conn.execute("PRAGMA user_version").fetchone()[0] == 0:
                for stmt in _SCHEMA.split(";"):
                    if stmt.strip():
                        self._conn.execute(stmt)
                self._conn.execute(f"PRAGMA user_version = {LEDGER_SCHEMA_VERSION}")
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise

    def _c(self) -> sqlite3.Connection:
        if self._conn is None:
            raise UnavailableError("banco de sessões fechado")
        return self._conn

    def _run(self, fn: Callable[[sqlite3.Connection], object]) -> object:
        try:
            return fn(self._c())
        except sqlite3.Error as exc:
            raise _unavailable(exc) from exc

    def _tx(self, fn: Callable[[sqlite3.Connection], object]) -> object:
        def go(c: sqlite3.Connection) -> object:
            c.execute("BEGIN IMMEDIATE")
            try:
                out = fn(c)
                c.execute("COMMIT")
                return out
            except BaseException:
                if c.in_transaction:
                    c.execute("ROLLBACK")
                raise
        return self._run(go)

    # ---- porta SessionLedger

    def open_session(
        self, *, started_at: datetime, boot_id: str | None, sample_interval_s: int,
        persist_interval_s: int, scope: Scope, energy_basis: EnergyBasis,
    ) -> Session:
        def go(c: sqlite3.Connection) -> Session:
            cur = c.execute(
                "INSERT INTO usage_sessions (started_at_utc, last_seen_utc, boot_id, "
                "sample_interval_s, persist_interval_s, scope, energy_basis) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_ts(started_at), _ts(started_at), boot_id, sample_interval_s,
                 persist_interval_s, scope.value, energy_basis.value),
            )
            return self._get(c, cur.lastrowid)[0]  # type: ignore[index]
        return self._tx(go)  # type: ignore[return-value]

    def heartbeat(self, session_id: int, last_seen_utc: datetime, acc: Accumulator) -> None:
        def go(c: sqlite3.Connection) -> None:
            c.execute(
                "UPDATE usage_sessions SET last_seen_utc = ?, measured_wh = ?, assumed_wh = ?, "
                "covered_s = ?, excluded_s = ?, partial_data = ?, stale = ? "
                "WHERE id = ? AND ended_at_utc IS NULL",
                (_ts(last_seen_utc), *_acc_params(acc), session_id),
            )
        self._run(go)

    def _close(self, c: sqlite3.Connection, session_id: int, ended_at: datetime,
               end_reason: EndReason, acc: Accumulator) -> Session:
        # Compare-and-swap: só fecha uma linha ainda aberta. Se outro processo já a encerrou
        # (recuperação/assunção), o dono antigo não sobrescreve esse fechamento.
        cur = c.execute(
            "UPDATE usage_sessions SET ended_at_utc = ?, last_seen_utc = ?, end_reason = ?, "
            "measured_wh = ?, assumed_wh = ?, covered_s = ?, excluded_s = ?, partial_data = ?, "
            "stale = ? WHERE id = ? AND ended_at_utc IS NULL",
            (_ts(ended_at), _ts(ended_at), end_reason.value, *_acc_params(acc), session_id),
        )
        got = self._get(c, session_id)
        if got is None:
            raise DomainError("session_not_found", f"sessão {session_id} não encontrada")
        if cur.rowcount == 0:
            raise DomainError(
                "session_already_open",
                f"a sessão {session_id} já foi encerrada por outro processo (assumida); "
                "este processo não pode mais gravá-la",
            )
        return got[0]

    def close(self, session_id: int, ended_at: datetime, end_reason: EndReason,
              acc: Accumulator) -> Session:
        return self._tx(lambda c: self._close(c, session_id, ended_at, end_reason, acc))  # type: ignore[return-value]

    def recover_open(
        self, decide: Callable[[Session], RecoveryDecision]
    ) -> tuple[Session, RecoveryDecision, Accumulator] | None:
        def go(c: sqlite3.Connection):
            row = c.execute(
                f"SELECT {_COLS} FROM usage_sessions WHERE ended_at_utc IS NULL "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            session, acc = _row_to_session(row)
            decision = decide(session)
            if not decision.alive:
                if decision.end_reason is None or decision.end_at is None:
                    raise DomainError("invalid_input", "decisão de recuperação sem fim ou motivo")
                session = self._close(c, session.id, decision.end_at, decision.end_reason, acc)
            return session, decision, acc
        return self._tx(go)  # type: ignore[return-value]

    @staticmethod
    def _get(c: sqlite3.Connection, session_id: int) -> tuple[Session, Accumulator] | None:
        row = c.execute(f"SELECT {_COLS} FROM usage_sessions WHERE id = ?", (session_id,)).fetchone()
        return None if row is None else _row_to_session(row)

    def get(self, session_id: int) -> tuple[Session, Accumulator] | None:
        return self._run(lambda c: self._get(c, session_id))  # type: ignore[return-value]

    def list_sessions(self, since: datetime | None = None, until: datetime | None = None
                      ) -> Sequence[tuple[Session, Accumulator]]:
        sql, args = f"SELECT {_COLS} FROM usage_sessions WHERE 1=1", []
        if since is not None:
            sql += " AND COALESCE(ended_at_utc, last_seen_utc) > ?"
            args.append(_ts(since))
        if until is not None:
            sql += " AND started_at_utc < ?"
            args.append(_ts(until))
        sql += " ORDER BY id"
        rows = self._run(lambda c: c.execute(sql, args).fetchall())
        return [_row_to_session(r) for r in rows]  # type: ignore[union-attr]
