"""Resolução da taxa em R$/kWh: tarifa ANEEL ou manual, mais adicional (D10, D11, D14)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..domain.energy_estimation.estimate import RateExtras, RateLookup, RateWindow
from ..domain.shared.errors import DomainError, InvalidInput
from ..domain.shared.parsing import parse_rate
from ..domain.tariff_catalog.model import ResolvedTariff, TariffProfile
from ..domain.tariff_catalog.selection import list_vigencias, select_tariff
from .ports import TariffSource

INCLUI_VALUES = ("tributos", "bandeira", "encargos", "nao-declarado")
ADICIONAL_TIPOS = ("bandeira", "tributos", "outro")
NOT_DECLARED = "nao-declarado"


@dataclass(frozen=True)
class TariffRequest:
    cnpj: str | None = None
    manual_total: str | None = None
    inclui: tuple[str, ...] = ()
    adicional_kwh: str | None = None
    adicional_tipo: str | None = None
    projetar_ultima_tarifa: bool = False


@dataclass(frozen=True)
class RateSelection:
    lookup: RateLookup
    extras: RateExtras
    warnings: tuple[str, ...]


def build_extras(request: TariffRequest) -> tuple[RateExtras, tuple[str, ...]]:
    """Política de tarifa manual e adicionais; o domínio soma e arredonda só o custo."""
    manual = request.manual_total is not None
    inclui = tuple(request.inclui)
    for item in inclui:
        if item not in INCLUI_VALUES:
            raise InvalidInput(f"--inclui inválido: {item!r}")
    if NOT_DECLARED in inclui and len(inclui) > 1:
        raise InvalidInput("--inclui nao-declarado não combina com outros valores")
    if inclui and not manual:
        raise InvalidInput("--inclui só vale com --tarifa-manual-total")
    if request.adicional_tipo is not None and request.adicional_tipo not in ADICIONAL_TIPOS:
        raise InvalidInput(f"--adicional-tipo inválido: {request.adicional_tipo!r}")
    if request.adicional_kwh is None:
        if request.adicional_tipo is not None:
            raise InvalidInput("--adicional-tipo exige --adicional-kwh")
        adicional = parse_rate("0")
    else:
        if request.adicional_tipo is None:
            raise InvalidInput("--adicional-kwh exige --adicional-tipo")
        adicional = parse_rate(request.adicional_kwh)

    warnings: list[str] = []
    if manual:
        declared = inclui or (NOT_DECLARED,)
        if request.adicional_kwh is not None:
            tipo = request.adicional_tipo
            if tipo in ("bandeira", "tributos") and tipo in declared:
                raise DomainError(
                    "double_inclusion", f"a tarifa manual já inclui {tipo}: adicional duplicaria"
                )
            if NOT_DECLARED in declared:
                raise DomainError(
                    "inclusion_undeclared",
                    "declare com --inclui o que a tarifa manual contém antes de somar adicional",
                )
    else:
        declared = ()
        if request.adicional_kwh is not None:
            warnings.append("base_excludes_taxes_and_flags")
    extras = RateExtras(adicional=adicional, tipo=request.adicional_tipo, inclusoes=declared)
    return extras, tuple(warnings)


def resolve_rate(request: TariffRequest, source: TariffSource) -> RateSelection:
    extras, warnings = build_extras(request)
    if request.manual_total is not None:
        window = RateWindow(rate=parse_rate(request.manual_total))
        return RateSelection(lambda day: window, extras, warnings)
    if not request.cnpj:
        raise InvalidInput("informe --tarifa-manual-total ou a distribuidora")
    records = list(source.tariff_records(request.cnpj))
    profile = TariffProfile(cnpj=request.cnpj)
    info = source.source_info()

    def lookup(day: date) -> RateWindow:
        try:
            record = select_tariff(records, profile, day)
            projected, last_day = False, record.fim
        except DomainError as exc:
            if not (exc.code == "tariff_not_in_effect" and request.projetar_ultima_tarifa):
                raise
            vigencias = list_vigencias(records, profile)
            if day <= max(r.fim for r in vigencias):
                raise
            record = max(vigencias, key=lambda r: (r.fim, r.inicio))
            projected, last_day = True, None
        resolved = ResolvedTariff.build(record, profile, info)
        return RateWindow(
            rate=resolved.rate, last_day=last_day, projected=projected,
            provenance=resolved.provenance,
        )

    return RateSelection(lookup, extras, warnings)
