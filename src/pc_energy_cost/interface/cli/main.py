"""CLI `pc-energy-cost`: argparse, serviços injetados, D13 e saída pt-BR/JSON v1."""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO

from ...application.estimate_cost import EstimateRequest, estimate_cost
from ...application.measure_power import measure_power
from ...application.ports import Clock, Store, SupplierChooser, SupplierSource, TariffSource
from ...application.refresh_catalog import RefreshRequest, RefreshResult
from ...application.resolve_supplier import SupplierAmbiguous, SupplierRequest, resolve_supplier
from ...application.resolve_tariff import TariffRequest
from ...domain.location_supplier.model import SupplierLink
from ...domain.metering.ports import MeteringProvider
from ...domain.shared.errors import DomainError, InvalidInput, UnavailableError
from ...domain.shared.parsing import parse_decimal
from . import json_schema, render_pt

RAPL_MAX_WATTS_RANGE = (Decimal(1), Decimal(10_000))


@dataclass(frozen=True)
class Services:
    """Dependências injetadas pela composição (ou por fakes nos testes)."""

    tariff_source: TariffSource
    clock: Clock
    supplier_source: SupplierSource | None = None
    store: Store | None = None
    chooser: SupplierChooser | None = None
    # atualiza/carrega o catálogo (composição liga CKAN, cache e store); None = sem catálogo
    refresh: Callable[[RefreshRequest], RefreshResult] | None = None
    # caminho do CSV `timestamp,watts` ⇒ provider
    series_provider: Callable[[Path], MeteringProvider] | None = None
    # `--rapl-max-watts` (ou None) ⇒ provider de contador; None = sem telemetria
    meter_provider: Callable[[Decimal | None], MeteringProvider] | None = None


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:  # type: ignore[override]
        raise InvalidInput(f"uso inválido: {message}")


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="pc-energy-cost",
        description="Estimativa do custo de energia atribuível a um PC "
        "(estimativa da energia atribuível, não fatura).",
        allow_abbrev=False,
    )
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    est = sub.add_parser("estimar", help="estima o custo em BRL", allow_abbrev=False)
    est.add_argument("--potencia", help="potência média em W")
    est.add_argument("--cenario-potencia-nominal", help="cenário com potência nominal em W")
    est.add_argument("--serie-csv", help="CSV timestamp,watts")
    est.add_argument("--horas", help="duração em horas")
    est.add_argument("--inicio", help="início ISO-8601 (naive = America/Sao_Paulo)")
    est.add_argument("--fim", help="fim ISO-8601 (naive = America/Sao_Paulo)")
    est.add_argument("--max-gap", help="maior intervalo coberto entre amostras (ex.: 5m, 1h)")
    est.add_argument("--trapezio", action="store_true", help="integração trapezoidal")
    est.add_argument("--municipio", help="código IBGE (7 dígitos)")
    est.add_argument("--distribuidora", help="CNPJ da distribuidora")
    est.add_argument("--tarifa-manual-total", help="tarifa all-in em R$/kWh")
    est.add_argument("--inclui", action="append", help="o que a tarifa manual inclui")
    est.add_argument("--adicional-kwh", help="adicional em R$/kWh")
    est.add_argument("--adicional-tipo", help="bandeira, tributos ou outro")
    est.add_argument("--projetar-ultima-tarifa", action="store_true")
    est.add_argument("--rapl-max-watts", help="potência máxima plausível do RAPL (1 a 10000 W)")
    est.add_argument("--permitir-cache-vencido", action="store_true")
    est.add_argument("--json", action="store_true", help="saída JSON schema v1")

    cat = sub.add_parser("atualizar-catalogo", help="atualiza o catálogo ANEEL", allow_abbrev=False)
    cat.add_argument("--permitir-cache-vencido", action="store_true")
    cat.add_argument("--json", action="store_true", help="saída JSON schema v1")
    return parser


def _parse_when(text: str | None, name: str) -> datetime | None:
    if text is None:
        return None
    if len(text) > 64:
        raise InvalidInput(f"{name}: texto longo demais")
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise InvalidInput(f"{name}: data/hora ISO-8601 inválida") from exc


def _inclui(values: Sequence[str] | None) -> tuple[str, ...]:
    # vazio sem --inclui: o `nao-declarado` só vale com tarifa manual (build_extras)
    return tuple(p.strip() for v in values or () for p in v.split(",") if p.strip())


def _rapl_max_watts(text: str | None) -> Decimal | None:
    if text is None:
        return None
    value = parse_decimal(text)
    low, high = RAPL_MAX_WATTS_RANGE
    if not low <= value <= high:
        raise InvalidInput("--rapl-max-watts deve estar entre 1 e 10000")
    return value


def _digits(text: str) -> str:
    return re.sub(r"[.\-/\s]", "", text)


def _estimar(
    args: argparse.Namespace, services: Services, tty: bool
) -> tuple[Any, SupplierLink | None, RefreshResult | None]:
    manual = args.tarifa_manual_total is not None
    inicio, fim = _parse_when(args.inicio, "--inicio"), _parse_when(args.fim, "--fim")
    rapl = _rapl_max_watts(args.rapl_max_watts)

    if not manual and args.municipio is None and args.distribuidora is None:
        # sem fonte de tarifa: falha antes de baixar o catálogo (que não seria usado)
        raise InvalidInput("informe --tarifa-manual-total, --municipio ou --distribuidora")

    catalog: RefreshResult | None = None
    if not manual and services.refresh is not None:
        catalog = services.refresh(RefreshRequest(args.permitir_cache_vencido))

    cnpj: str | None = _digits(args.distribuidora) if args.distribuidora else None
    supplier: SupplierLink | None = None
    if not manual and args.municipio is not None:
        if services.supplier_source is None or services.store is None:
            raise UnavailableError("resolução de município indisponível neste ambiente")
        supplier = resolve_supplier(
            SupplierRequest(args.municipio, args.distribuidora, tty and not args.json, args.json),
            services.supplier_source,
            services.store,
            services.chooser,
        )
        cnpj = supplier.distributor.cnpj
    tariff = TariffRequest(
        cnpj=cnpj,
        manual_total=args.tarifa_manual_total,
        inclui=_inclui(args.inclui),
        adicional_kwh=args.adicional_kwh,
        adicional_tipo=args.adicional_tipo,
        projetar_ultima_tarifa=args.projetar_ultima_tarifa,
    )

    samples = None
    metered_scope = None
    meter_warnings: tuple[str, ...] = ()
    pre_excluded: tuple[Any, ...] = ()
    coverage_source = "csv"
    if args.serie_csv is not None:
        if services.series_provider is None:
            raise UnavailableError("leitura de série CSV indisponível neste ambiente")
        samples = measure_power(services.series_provider(Path(args.serie_csv))).samples
    elif args.potencia is None and args.cenario_potencia_nominal is None:
        if services.meter_provider is None:
            raise UnavailableError("telemetria indisponível: nenhum provider de medição configurado")
        result = measure_power(services.meter_provider(rapl))
        samples, metered_scope, meter_warnings = result.samples, result.scope, result.warnings
        pre_excluded, coverage_source = result.excluded, "counter"
        if result.window is not None:
            inicio, fim = inicio or result.window[0], fim or result.window[1]

    request = EstimateRequest(
        tariff=tariff,
        potencia=args.potencia,
        cenario_potencia_nominal=args.cenario_potencia_nominal,
        samples=samples,
        horas=args.horas,
        inicio=inicio,
        fim=fim,
        max_gap=args.max_gap,
        trapezio=args.trapezio,
        pre_excluded=pre_excluded,
        coverage_source=coverage_source,
    )
    estimate = estimate_cost(request, services.tariff_source, services.clock)
    if metered_scope is not None:
        warnings = tuple(dict.fromkeys((*estimate.warnings, *meter_warnings)))
        estimate = dataclasses.replace(estimate, scope=metered_scope, warnings=warnings)
    return estimate, supplier, catalog


def _emit(text: str, stream: TextIO) -> None:
    stream.write(text)


def run(
    argv: Sequence[str],
    services: Services,
    stdin_is_tty: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    as_json = "--json" in argv
    try:
        try:
            args = _build_parser().parse_args(list(argv))
        except SystemExit as exc:  # só `--help`
            return int(exc.code or 0)
        as_json = args.json
        if args.command == "atualizar-catalogo":
            if services.refresh is None:
                raise UnavailableError("atualização de catálogo indisponível neste ambiente")
            refreshed = services.refresh(RefreshRequest(args.permitir_cache_vencido))
            if as_json:
                doc = json_schema.success_document(
                    args.command, json_schema.catalog_to_json(refreshed) or {}
                )
                _emit(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", out)
            else:
                _emit(render_pt.render_refresh(refreshed), out)
            return 0
        estimate, supplier, catalog = _estimar(args, services, stdin_is_tty)
        if as_json:
            result = json_schema.estimate_to_json(estimate, render_pt.LABEL, supplier, catalog)
            doc = json_schema.success_document(args.command, result)
            _emit(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", out)
        else:
            _emit(render_pt.render_estimate(estimate, supplier, catalog), out)
        return 0
    except DomainError as exc:
        if as_json:
            doc = json_schema.domain_error_document(exc)
            _emit(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", out)
        else:
            candidates = exc.candidates if isinstance(exc, SupplierAmbiguous) else ()
            _emit(render_pt.render_error(exc.code, exc.message, candidates), err)
        return exc.exit_code
