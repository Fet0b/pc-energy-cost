"""Resolução pura município → distribuidora a partir do join IndQual × DEC/FEC."""

from __future__ import annotations

from collections import defaultdict

from ..tariff_catalog.model import Distributor
from .model import (
    OFFICIAL_CONFIDENCE,
    OFFICIAL_SOURCE,
    USER_CONFIDENCE,
    USER_SOURCE,
    Ambiguous,
    CoverageIndex,
    Municipality,
    Resolved,
    SupplierLink,
    Unsupported,
)


def resolve_supplier(ibge_code: str, index: CoverageIndex) -> Resolved | Ambiguous | Unsupported:
    """Por conjunto vale só o(s) agente(s) do maior ano; a chave do vínculo é o CNPJ."""
    municipality = index.municipalities.get(ibge_code)
    if municipality is None:
        return Unsupported(ibge_code)
    count: dict[str, int] = defaultdict(int)
    years: dict[str, set[int]] = defaultdict(set)
    siglas: dict[str, set[str]] = defaultdict(set)
    sem_agente: list[str] = []
    for conjunto in dict.fromkeys(index.conjuntos.get(ibge_code, ())):
        rows = index.agents.get(conjunto, ())
        if not rows:
            sem_agente.append(conjunto)
            continue
        latest = max(r.year for r in rows)
        latest_cnpjs = {r.cnpj.strip() for r in rows if r.year == latest}
        for cnpj in latest_cnpjs:  # um conjunto conta uma vez por CNPJ (DEC e FEC repetem a linha)
            count[cnpj] += 1
            years[cnpj].add(latest)
        for r in rows:
            if r.year == latest:
                siglas[r.cnpj.strip()].add(r.sigla.strip())
    if not count:
        return Unsupported(ibge_code)
    missing = tuple(sorted(sem_agente, key=lambda c: (len(c), c)))
    links = tuple(
        SupplierLink(
            municipality=municipality,
            distributor=Distributor(cnpj=cnpj, sig_agente=min(siglas[cnpj])),
            source=OFFICIAL_SOURCE,
            evidence={
                "n_conjuntos": count[cnpj],
                "conjuntos_sem_agente": missing,
                "ano_limite_usado": tuple(sorted(years[cnpj])),
            },
            confidence=OFFICIAL_CONFIDENCE,
        )
        for cnpj in sorted(count, key=lambda c: (-count[c], c))
    )
    return Resolved(links[0]) if len(links) == 1 else Ambiguous(links)


def user_confirmed_link(municipality: Municipality, distributor: Distributor) -> SupplierLink:
    """Escolha do usuário: vínculo separado, nunca mesclado ao oficial."""
    return SupplierLink(
        municipality=municipality,
        distributor=distributor,
        source=USER_SOURCE,
        evidence={},
        confidence=USER_CONFIDENCE,
        user_confirmed=True,
    )
