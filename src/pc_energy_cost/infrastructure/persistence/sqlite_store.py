"""Store SQLite: tarifas indexadas, cobertura município↔conjunto↔agente, vínculos, preferências."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from ...domain.location_supplier.model import (
    Ambiguous,
    AgentLimit,
    CoverageIndex,
    Municipality,
    Resolved,
    SupplierLink,
    USER_CONFIDENCE,
    USER_SOURCE,
)
from ...domain.location_supplier.resolver import resolve_supplier
from ...domain.shared.errors import UnavailableError
from ...domain.tariff_catalog.model import Distributor, SourceInfo, TariffRecord

_MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE tariffs (
        id INTEGER PRIMARY KEY,
        DatGeracaoConjuntoDados TEXT NOT NULL,
        DscREH TEXT NOT NULL,
        SigAgente TEXT NOT NULL,
        NumCNPJDistribuidora TEXT NOT NULL,
        DatInicioVigencia TEXT NOT NULL,
        DatFimVigencia TEXT NOT NULL,
        DscBaseTarifaria TEXT NOT NULL,
        DscSubGrupo TEXT NOT NULL,
        DscModalidadeTarifaria TEXT NOT NULL,
        DscClasse TEXT NOT NULL,
        DscSubClasse TEXT NOT NULL,
        DscDetalhe TEXT NOT NULL,
        NomPostoTarifario TEXT NOT NULL,
        DscUnidadeTerciaria TEXT NOT NULL,
        SigAgenteAcessante TEXT NOT NULL,
        VlrTUSD TEXT NOT NULL,
        VlrTE TEXT NOT NULL,
        source_sha256 TEXT NOT NULL
    );
    CREATE INDEX idx_tariffs_cnpj_vigencia
        ON tariffs (NumCNPJDistribuidora, DatInicioVigencia, DatFimVigencia);
    CREATE TABLE tariff_source (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        url TEXT NOT NULL,
        resource_id TEXT NOT NULL,
        metadata_modified TEXT NOT NULL,
        last_modified TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        sha256 TEXT NOT NULL
    );
    CREATE TABLE municipalities (
        ibge_code TEXT PRIMARY KEY, name TEXT NOT NULL, uf TEXT NOT NULL
    );
    CREATE TABLE municipality_conjuntos (
        pos INTEGER PRIMARY KEY, ibge_code TEXT NOT NULL, conjunto TEXT NOT NULL
    );
    CREATE INDEX idx_muni_conjuntos ON municipality_conjuntos (ibge_code);
    CREATE TABLE agent_limits (
        pos INTEGER PRIMARY KEY, conjunto TEXT NOT NULL, cnpj TEXT NOT NULL,
        sigla TEXT NOT NULL, year INTEGER NOT NULL
    );
    CREATE INDEX idx_agent_limits ON agent_limits (conjunto);
    CREATE TABLE user_links (
        ibge_code TEXT PRIMARY KEY,
        name TEXT NOT NULL, uf TEXT NOT NULL,
        cnpj TEXT NOT NULL, sig_agente TEXT NOT NULL,
        source TEXT NOT NULL, confidence TEXT NOT NULL, evidence TEXT NOT NULL
    );
    CREATE TABLE preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE cache_index (
        key TEXT PRIMARY KEY, sha256 TEXT NOT NULL, stored_at TEXT NOT NULL
    );
    """,
)
SCHEMA_VERSION = len(_MIGRATIONS)

_TARIFF_COLUMNS = (
    "DatGeracaoConjuntoDados", "DscREH", "SigAgente", "NumCNPJDistribuidora",
    "DatInicioVigencia", "DatFimVigencia", "DscBaseTarifaria", "DscSubGrupo",
    "DscModalidadeTarifaria", "DscClasse", "DscSubClasse", "DscDetalhe",
    "NomPostoTarifario", "DscUnidadeTerciaria", "SigAgenteAcessante", "VlrTUSD", "VlrTE",
)
_INSERT_TARIFF = (
    f"INSERT INTO tariffs ({', '.join(_TARIFF_COLUMNS)}, source_sha256) "
    f"VALUES ({', '.join('?' * (len(_TARIFF_COLUMNS) + 1))})"
)
_SELECT_TARIFF = (
    f"SELECT {', '.join(_TARIFF_COLUMNS)} FROM tariffs "
    "WHERE NumCNPJDistribuidora = ? ORDER BY id"
)


def _jsonable(value: Any) -> Any:
    return list(value) if isinstance(value, (tuple, list)) else value


def _restore(value: Any) -> Any:
    return tuple(_restore(v) for v in value) if isinstance(value, list) else value


class SqliteStore:
    """Implementa `TariffSource`, `SupplierSource` e `Store`; SQL sempre parametrizado."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, isolation_level=None)
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    def _migrate(self) -> None:
        current = self._conn.execute("PRAGMA user_version").fetchone()[0]
        for version in range(current, SCHEMA_VERSION):
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for statement in _MIGRATIONS[version].split(";"):
                    if statement.strip():
                        self._conn.execute(statement)
                self._conn.execute(f"PRAGMA user_version = {int(version) + 1}")
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def _transaction(self) -> _Tx:
        return _Tx(self._conn)

    # --- tarifas ---------------------------------------------------------------------------
    def load_tariffs(self, records: Iterable[TariffRecord], source: SourceInfo) -> int:
        """Substitui o catálogo numa transação; falha ⇒ rollback, carga anterior intacta."""
        count = 0
        with self._transaction():
            self._conn.execute("DELETE FROM tariffs")
            self._conn.execute("DELETE FROM tariff_source")
            for r in records:
                self._conn.execute(
                    _INSERT_TARIFF,
                    (
                        r.data_geracao.isoformat(), r.reh, r.sig_agente, r.cnpj,
                        r.inicio.isoformat(), r.fim.isoformat(), r.base, r.subgrupo,
                        r.modalidade, r.classe, r.subclasse, r.detalhe, r.posto, r.unidade,
                        r.agente_acessante, str(r.tusd), str(r.te), source.sha256,
                    ),
                )
                count += 1
            self._conn.execute(
                "INSERT INTO tariff_source VALUES (1, ?, ?, ?, ?, ?, ?)",
                (
                    source.url, source.resource_id, source.metadata_modified,
                    source.last_modified, source.fetched_at.isoformat(), source.sha256,
                ),
            )
        return count

    def tariff_records(self, cnpj: str) -> Sequence[TariffRecord]:
        rows = self._conn.execute(_SELECT_TARIFF, (cnpj,)).fetchall()
        return tuple(
            TariffRecord(
                data_geracao=date.fromisoformat(r[0]), reh=r[1], sig_agente=r[2], cnpj=r[3],
                inicio=date.fromisoformat(r[4]), fim=date.fromisoformat(r[5]), base=r[6],
                subgrupo=r[7], modalidade=r[8], classe=r[9], subclasse=r[10], detalhe=r[11],
                posto=r[12], unidade=r[13], agente_acessante=r[14],
                tusd=Decimal(r[15]), te=Decimal(r[16]),
            )
            for r in rows
        )

    def source_info(self) -> SourceInfo:
        row = self._conn.execute(
            "SELECT url, resource_id, metadata_modified, last_modified, fetched_at, sha256 "
            "FROM tariff_source WHERE id = 1"
        ).fetchone()
        if row is None:
            raise UnavailableError("catálogo de tarifas não carregado (rode atualizar-catalogo)")
        return SourceInfo(
            url=row[0], resource_id=row[1], metadata_modified=row[2], last_modified=row[3],
            fetched_at=datetime.fromisoformat(row[4]), sha256=row[5],
        )

    def tariff_vigencia(self) -> tuple[date, date] | None:
        row = self._conn.execute(
            "SELECT MIN(DatInicioVigencia), MAX(DatFimVigencia) FROM tariffs"
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return date.fromisoformat(row[0]), date.fromisoformat(row[1])

    # --- cobertura e vínculos --------------------------------------------------------------
    def load_coverage(self, index: CoverageIndex) -> None:
        """Substitui a cobertura oficial; vínculos `user_confirmed` não são tocados."""
        with self._transaction():
            for table in ("municipalities", "municipality_conjuntos", "agent_limits"):
                self._conn.execute(f"DELETE FROM {table}")  # nome fixo, não vem de entrada
            for code, m in index.municipalities.items():
                self._conn.execute(
                    "INSERT INTO municipalities VALUES (?, ?, ?)", (code, m.name, m.uf)
                )
            for code, conjuntos in index.conjuntos.items():
                self._conn.executemany(
                    "INSERT INTO municipality_conjuntos (ibge_code, conjunto) VALUES (?, ?)",
                    [(code, c) for c in conjuntos],
                )
            for conjunto, agents in index.agents.items():
                self._conn.executemany(
                    "INSERT INTO agent_limits (conjunto, cnpj, sigla, year) VALUES (?, ?, ?, ?)",
                    [(conjunto, a.cnpj, a.sigla, a.year) for a in agents],
                )

    def official_links(self, ibge_code: str) -> Sequence[SupplierLink]:
        row = self._conn.execute(
            "SELECT name, uf FROM municipalities WHERE ibge_code = ?", (ibge_code,)
        ).fetchone()
        if row is None:
            return ()
        conjuntos = tuple(
            r[0]
            for r in self._conn.execute(
                "SELECT conjunto FROM municipality_conjuntos WHERE ibge_code = ? ORDER BY pos",
                (ibge_code,),
            )
        )
        agents: dict[str, tuple[AgentLimit, ...]] = {}
        for conjunto in dict.fromkeys(conjuntos):
            rows = self._conn.execute(
                "SELECT cnpj, sigla, year FROM agent_limits WHERE conjunto = ? ORDER BY pos",
                (conjunto,),
            ).fetchall()
            if rows:
                agents[conjunto] = tuple(AgentLimit(c, s, y) for c, s, y in rows)
        index = CoverageIndex(
            {ibge_code: Municipality(ibge_code, row[0], row[1])}, {ibge_code: conjuntos}, agents
        )
        result = resolve_supplier(ibge_code, index)
        if isinstance(result, Resolved):
            return (result.link,)
        if isinstance(result, Ambiguous):
            return result.candidates
        return ()

    def save_user_link(self, link: SupplierLink) -> None:
        m, d = link.municipality, link.distributor
        evidence = json.dumps({k: _jsonable(v) for k, v in link.evidence.items()})
        with self._transaction():
            self._conn.execute(
                "INSERT OR REPLACE INTO user_links VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (m.ibge_code, m.name, m.uf, d.cnpj, d.sig_agente, USER_SOURCE,
                 USER_CONFIDENCE, evidence),
            )

    def user_link(self, ibge_code: str) -> SupplierLink | None:
        row = self._conn.execute(
            "SELECT name, uf, cnpj, sig_agente, source, confidence, evidence "
            "FROM user_links WHERE ibge_code = ?",
            (ibge_code,),
        ).fetchone()
        if row is None:
            return None
        return SupplierLink(
            municipality=Municipality(ibge_code, row[0], row[1]),
            distributor=Distributor(cnpj=row[2], sig_agente=row[3]),
            source=row[4],
            evidence={k: _restore(v) for k, v in json.loads(row[6]).items()},
            confidence=row[5],
            user_confirmed=True,
        )

    # --- preferências e índice do cache ----------------------------------------------------
    def get_preference(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM preferences WHERE key = ?", (key,)).fetchone()
        return None if row is None else row[0]

    def set_preference(self, key: str, value: str) -> None:
        with self._transaction():
            self._conn.execute(
                "INSERT OR REPLACE INTO preferences VALUES (?, ?)", (key, value)
            )

    def get_cache_entry(self, key: str) -> tuple[str, str] | None:
        row = self._conn.execute(
            "SELECT sha256, stored_at FROM cache_index WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else (row[0], row[1])

    def set_cache_entry(self, key: str, sha256: str, stored_at: str) -> None:
        with self._transaction():
            self._conn.execute(
                "INSERT OR REPLACE INTO cache_index VALUES (?, ?, ?)", (key, sha256, stored_at)
            )


class _Tx:
    """Transação explícita: COMMIT na saída normal, ROLLBACK em qualquer exceção."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> None:
        self._conn.execute("BEGIN IMMEDIATE")

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._conn.execute("ROLLBACK" if exc_type else "COMMIT")
