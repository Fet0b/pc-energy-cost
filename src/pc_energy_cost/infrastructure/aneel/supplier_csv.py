"""Parsers do IndQual município (cp1252, 5 colunas) e DEC/FEC limite (`utf-8-sig`, 8 colunas)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from ...domain.location_supplier.model import AgentLimit, CoverageIndex, Municipality
from ...domain.shared.errors import DomainError
from .csv_common import check_header, iter_rows, mismatch

INDQUAL_ENCODING = "cp1252"
LIMITE_ENCODING = "utf-8-sig"
INDQUAL_COLUMNS: tuple[str, ...] = (
    "DatGeracaoConjuntoDados", "IdeConjUnidConsumidoras", "CodMunicipio", "NomMunicipio", "SigUF",
)
LIMITE_COLUMNS: tuple[str, ...] = (
    "DatGeracaoConjuntoDados", "SigAgente", "NumCNPJ", "IdeConjUndConsumidoras",
    "DscConjUndConsumidoras", "SigIndicador", "AnoLimiteQualidade", "VlrLimite",
)


def check_indqual_header(path: Path) -> None:
    check_header(path, INDQUAL_COLUMNS, INDQUAL_ENCODING, "indqual")


def check_limite_header(path: Path) -> None:
    check_header(path, LIMITE_COLUMNS, LIMITE_ENCODING, "limite")


def read_indqual(
    path: Path,
) -> tuple[dict[str, Municipality], dict[str, tuple[str, ...]]]:
    """Municípios por código IBGE e conjuntos de cada município (ordem do arquivo)."""
    municipalities: dict[str, Municipality] = {}
    conjuntos: dict[str, list[str]] = defaultdict(list)
    for row in iter_rows(path, INDQUAL_COLUMNS, INDQUAL_ENCODING, "indqual"):
        try:
            code = row["CodMunicipio"]
            municipalities[code] = Municipality(code, row["NomMunicipio"], row["SigUF"])
        except DomainError as exc:
            raise mismatch(f"indqual: linha inválida ({exc.message})") from exc
        conjuntos[code].append(row["IdeConjUnidConsumidoras"])
    return municipalities, {k: tuple(v) for k, v in conjuntos.items()}


def read_limite(path: Path) -> dict[str, tuple[AgentLimit, ...]]:
    """Agentes por conjunto, com siglas sem espaços; o CNPJ é a chave."""
    agents: dict[str, list[AgentLimit]] = defaultdict(list)
    for row in iter_rows(path, LIMITE_COLUMNS, LIMITE_ENCODING, "limite"):
        try:
            year = int(row["AnoLimiteQualidade"])
        except ValueError as exc:
            raise mismatch("limite: AnoLimiteQualidade inválido") from exc
        agents[row["IdeConjUndConsumidoras"]].append(
            AgentLimit(row["NumCNPJ"], row["SigAgente"], year)
        )
    return {k: tuple(v) for k, v in agents.items()}


def build_coverage_index(indqual: Path, limite: Path) -> CoverageIndex:
    municipalities, conjuntos = read_indqual(indqual)
    return CoverageIndex(municipalities, conjuntos, read_limite(limite))
