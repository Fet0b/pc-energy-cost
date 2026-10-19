"""Modelo do mapeamento município ↔ distribuidora e resultados da resolução."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from ..shared.errors import InvalidInput
from ..tariff_catalog.model import Distributor

OFFICIAL_SOURCE = "aneel:indqual+dec-fec"
OFFICIAL_CONFIDENCE = "official_indicator_join"
USER_SOURCE = "user"
USER_CONFIDENCE = "user_confirmed"


@dataclass(frozen=True)
class Municipality:
    ibge_code: str
    name: str
    uf: str

    def __post_init__(self) -> None:
        if not (len(self.ibge_code) == 7 and self.ibge_code.isascii() and self.ibge_code.isdigit()):
            raise InvalidInput("município: código IBGE deve ter 7 dígitos")


@dataclass(frozen=True)
class SupplierLink:
    municipality: Municipality
    distributor: Distributor
    source: str
    evidence: Mapping[str, Any]
    confidence: str
    user_confirmed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))


@dataclass(frozen=True)
class AgentLimit:
    """Linha do DEC/FEC limite: agente de um conjunto em um `AnoLimiteQualidade`."""

    cnpj: str
    sigla: str
    year: int


@dataclass(frozen=True)
class CoverageIndex:
    """Estruturas em memória: município↔conjuntos e conjunto↔agentes (sem I/O)."""

    municipalities: Mapping[str, Municipality]
    conjuntos: Mapping[str, tuple[str, ...]]
    agents: Mapping[str, tuple[AgentLimit, ...]]


@dataclass(frozen=True)
class Resolved:
    link: SupplierLink


@dataclass(frozen=True)
class Ambiguous:
    candidates: tuple[SupplierLink, ...]


@dataclass(frozen=True)
class Unsupported:
    ibge_code: str
    reason: str = "no_coverage"
