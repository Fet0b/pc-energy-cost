"""Caso de uso: município (IBGE) ⇒ distribuidora, com a política D8 (nunca "predominante")."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..domain.location_supplier.model import SupplierLink
from ..domain.location_supplier.resolver import user_confirmed_link
from ..domain.shared.errors import DomainError, InvalidInput
from .ports import Store, SupplierChooser, SupplierSource


class SupplierAmbiguous(DomainError):
    """`supplier_ambiguous` (exit 3) carregando os candidatos para a saída."""

    def __init__(self, candidates: tuple[SupplierLink, ...]) -> None:
        names = ", ".join(f"{c.distributor.sig_agente} ({c.distributor.cnpj})" for c in candidates)
        super().__init__(
            "supplier_ambiguous",
            f"município atendido por mais de uma distribuidora: {names}; "
            "use --distribuidora <CNPJ>",
        )
        self.candidates = candidates


@dataclass(frozen=True)
class SupplierRequest:
    ibge_code: str
    distribuidora: str | None = None
    tty: bool = False
    json: bool = False


def _digits(cnpj: str) -> str:
    return re.sub(r"[.\-/\s]", "", cnpj)


def resolve_supplier(
    request: SupplierRequest,
    source: SupplierSource,
    store: Store,
    chooser: SupplierChooser | None = None,
) -> SupplierLink:
    code = request.ibge_code
    if not (len(code) == 7 and code.isascii() and code.isdigit()):
        raise InvalidInput("código IBGE deve ter 7 dígitos")
    official = tuple(source.official_links(code))
    wanted = _digits(request.distribuidora) if request.distribuidora else None

    if wanted is None:
        saved = source.user_link(code)
        if saved is not None:
            return saved
    if not official:
        raise DomainError("unsupported", f"sem cobertura de distribuidora para o município {code}")

    if wanted is not None:
        match = next((c for c in official if _digits(c.distributor.cnpj) == wanted), None)
        if match is None:
            options = ", ".join(c.distributor.cnpj for c in official)
            raise InvalidInput(
                f"distribuidora {request.distribuidora!r} não consta entre as do município: {options}"
            )
        return _confirm(match, official, store)

    if len(official) == 1:
        return official[0]
    if request.tty and not request.json and chooser is not None:
        chosen = chooser.choose(official)
        if chosen is not None:
            return _confirm(chosen, official, store)
    raise SupplierAmbiguous(official)


def _confirm(
    choice: SupplierLink, official: tuple[SupplierLink, ...], store: Store
) -> SupplierLink:
    if len(official) == 1:
        return choice  # sem ambiguidade não há escolha do usuário a persistir
    link = user_confirmed_link(choice.municipality, choice.distributor)
    store.save_user_link(link)
    return link
