"""CLI `pc-energy-cost`: argparse, serviços injetados, D13 e saída pt-BR/JSON v1."""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO

from ...application.estimate_cost import EstimateRequest, estimate_cost
from ...application.measure_power import measure_power
from ...application.export_summary import export_summary
from ...application.ports import (
    BootIdentity,
    Clock,
    LiveMeter,
    MonotonicClock,
    SessionLedger,
    Store,
    SummaryExporter,
    SupplierChooser,
    SupplierSource,
    TariffSource,
)
from ...application.refresh_catalog import RefreshRequest, RefreshResult
from ...application.resolve_supplier import SupplierAmbiguous, SupplierRequest, resolve_supplier
from ...application.resolve_tariff import TariffRequest, build_extras
from ...application.session_report import COST_LABEL, list_sessions, period_cost
from ...application.track_session import TrackRequest, TrackView, track_session
from ...domain.location_supplier.model import SupplierLink
from ...domain.metering.ports import MeteringProvider
from ...domain.energy_estimation.schedule import load_zone
from ...domain.shared.errors import DomainError, InvalidInput, UnavailableError
from ...domain.usage_session.lifecycle import PROVISIONAL
from ...domain.shared.parsing import (
    parse_decimal,
    parse_hours,
    parse_max_gap,
    parse_rate,
    parse_watts,
)
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
    # --- sessões (`sessao`): todos opcionais; o ledger só abre quando um subcomando o usa ---
    session_ledger: SessionLedger | None = None
    live_meter: Callable[[], LiveMeter] | None = None
    mono: MonotonicClock | None = None
    boot: BootIdentity | None = None
    exporter: SummaryExporter | None = None
    sleep: Callable[[float], None] | None = None  # None = time.sleep
    should_stop: Callable[[], bool] | None = None  # None = só Ctrl+C encerra


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

    _add_session_parsers(sub)

    cat = sub.add_parser("atualizar-catalogo", help="atualiza o catálogo ANEEL", allow_abbrev=False)
    cat.add_argument("--permitir-cache-vencido", action="store_true")
    cat.add_argument("--json", action="store_true", help="saída JSON schema v1")
    return parser


def _add_tariff_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--municipio", help="código IBGE (7 dígitos)")
    p.add_argument("--distribuidora", help="CNPJ da distribuidora")
    p.add_argument("--tarifa-manual-total", help="tarifa all-in em R$/kWh")
    p.add_argument("--inclui", action="append", help="o que a tarifa manual inclui")
    p.add_argument("--adicional-kwh", help="adicional em R$/kWh")
    p.add_argument("--adicional-tipo", help="bandeira, tributos ou outro")
    p.add_argument("--projetar-ultima-tarifa", action="store_true")
    p.add_argument("--permitir-cache-vencido", action="store_true")


def _add_session_parsers(sub: Any) -> None:
    ses = sub.add_parser("sessao", help="sessões de uso e custo em tempo real", allow_abbrev=False)
    ssub = ses.add_subparsers(dest="session_command", required=True, parser_class=_Parser)

    ac = ssub.add_parser("acompanhar", help="acompanha o custo ao vivo (Ctrl+C encerra)",
                         allow_abbrev=False)
    ac.add_argument("--intervalo", default=str(PROVISIONAL.sample_interval_s),
                    help="segundos entre atualizações")
    ac.add_argument("--persistir-a-cada", default=str(PROVISIONAL.persist_interval_s),
                    help="segundos entre gravações do progresso")
    ac.add_argument("--potencia", help="potência informada em W (usada no lugar do sensor)")
    ac.add_argument("--completar-com-potencia", action="store_true",
                    help="preenche com a potência informada os trechos sem leitura (rotulado assumido)")
    _add_tariff_args(ac)
    ac.add_argument("--json", action="store_true", help="uma linha JSON por atualização")

    ls = ssub.add_parser("listar", help="lista as sessões", allow_abbrev=False)
    ls.add_argument("--desde", help="ISO-8601 (naive = America/Sao_Paulo)")
    ls.add_argument("--ate", help="ISO-8601 (naive = America/Sao_Paulo)")
    ls.add_argument("--json", action="store_true", help="saída JSON schema v1")

    co = ssub.add_parser("custo", help="custo estimado das sessões no período", allow_abbrev=False)
    co.add_argument("--desde", required=True, help="ISO-8601 (naive = America/Sao_Paulo)")
    co.add_argument("--ate", help="ISO-8601 (padrão: agora)")
    _add_tariff_args(co)
    co.add_argument("--json", action="store_true", help="saída JSON schema v1")

    ex = ssub.add_parser("exportar", help="texto Proxmox-compatível do custo de uma sessão",
                         allow_abbrev=False)
    ex.add_argument("sessao_id", help="id da sessão")
    _add_tariff_args(ex)
    ex.add_argument("--json", action="store_true", help="saída JSON schema v1")


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


def _is_ascii_digits(text: str, length: int) -> bool:
    return len(text) == length and text.isascii() and text.isdigit()


def _check_window(args: argparse.Namespace, inicio: datetime | None, fim: datetime | None) -> None:
    """Duração/intervalo checáveis sem rede; espelha a precedência de `estimate_cost` (horas > janela)."""
    if inicio is not None and fim is not None and args.horas is None:
        zone = load_zone()
        start = inicio if inicio.tzinfo else inicio.replace(tzinfo=zone)
        end = fim if fim.tzinfo else fim.replace(tzinfo=zone)
        # série CSV integra a janela e exige fim > início; potência fixa aceita janela vazia
        if end < start or (args.serie_csv is not None and end == start):
            raise InvalidInput("o fim do intervalo deve ser posterior ao início", code="invalid_interval")
    if args.serie_csv is None and (args.potencia or args.cenario_potencia_nominal):
        if args.horas is None and (inicio is None or fim is None):
            raise InvalidInput("informe --horas ou --inicio/--fim")


def _estimar(
    args: argparse.Namespace, services: Services, tty: bool
) -> tuple[Any, SupplierLink | None, RefreshResult | None]:
    manual = args.tarifa_manual_total is not None
    inicio, fim = _parse_when(args.inicio, "--inicio"), _parse_when(args.fim, "--fim")
    rapl = _rapl_max_watts(args.rapl_max_watts)
    _check_window(args, inicio, fim)

    if args.municipio is not None and not _is_ascii_digits(args.municipio, 7):
        raise InvalidInput("--municipio deve ser um código IBGE de 7 dígitos")
    if args.distribuidora is not None and not _is_ascii_digits(_digits(args.distribuidora), 14):
        raise InvalidInput("--distribuidora deve ser um CNPJ de 14 dígitos")
    if not manual and args.municipio is None and args.distribuidora is None:
        # sem fonte de tarifa: falha antes de baixar o catálogo (que não seria usado)
        raise InvalidInput("informe --tarifa-manual-total, --municipio ou --distribuidora")

    # toda validação barata (potência, números, tarifa/adicionais, CSV) antes de rede/catálogo
    if sum(v is not None for v in (args.potencia, args.cenario_potencia_nominal, args.serie_csv)) > 1:
        raise InvalidInput(
            "informe exatamente uma fonte de potência: potência média, série ou cenário nominal"
        )
    for watts in (args.potencia, args.cenario_potencia_nominal):
        if watts is not None:
            parse_watts(watts)
    if args.horas is not None:
        parse_hours(args.horas)
    if args.max_gap is not None:
        parse_max_gap(args.max_gap)
    cnpj: str | None = _digits(args.distribuidora) if args.distribuidora else None
    tariff = TariffRequest(
        cnpj=cnpj,
        manual_total=args.tarifa_manual_total,
        inclui=_inclui(args.inclui),
        adicional_kwh=args.adicional_kwh,
        adicional_tipo=args.adicional_tipo,
        projetar_ultima_tarifa=args.projetar_ultima_tarifa,
    )
    build_extras(tariff)
    if manual:
        parse_rate(args.tarifa_manual_total)

    samples = None
    metered_scope = None
    meter_warnings: tuple[str, ...] = ()
    pre_excluded: tuple[Any, ...] = ()
    coverage_source = "csv"
    if args.serie_csv is not None:
        if services.series_provider is None:
            raise UnavailableError("leitura de série CSV indisponível neste ambiente")
        samples = measure_power(services.series_provider(Path(args.serie_csv))).samples

    catalog: RefreshResult | None = None
    if not manual and services.refresh is not None:
        catalog = services.refresh(RefreshRequest(args.permitir_cache_vencido))

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
        tariff = dataclasses.replace(tariff, cnpj=supplier.distributor.cnpj)

    if args.serie_csv is None and args.potencia is None and args.cenario_potencia_nominal is None:
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


# -- sessões -----------------------------------------------------------------------------------


def _need(value: Any, what: str) -> Any:
    if value is None:
        raise UnavailableError(f"{what} indisponível neste ambiente")
    return value


def _seconds(text: str, name: str) -> int:
    if not re.fullmatch(r"[0-9]{1,9}", text):
        raise InvalidInput(f"{name} deve ser um número inteiro de segundos")
    return int(text)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=load_zone())
    return value


def _session_tariff(
    args: argparse.Namespace, services: Services, tty: bool, required: bool
) -> TariffRequest | None:
    """Valida e resolve a fonte de tarifa (catálogo só em cache/refresh ANTES do laço)."""
    manual = args.tarifa_manual_total is not None
    if args.municipio is not None and not _is_ascii_digits(args.municipio, 7):
        raise InvalidInput("--municipio deve ser um código IBGE de 7 dígitos")
    if args.distribuidora is not None and not _is_ascii_digits(_digits(args.distribuidora), 14):
        raise InvalidInput("--distribuidora deve ser um CNPJ de 14 dígitos")
    if not manual and args.municipio is None and args.distribuidora is None:
        if required:
            raise InvalidInput("informe --tarifa-manual-total, --municipio ou --distribuidora")
        return None
    tariff = TariffRequest(
        cnpj=_digits(args.distribuidora) if args.distribuidora else None,
        manual_total=args.tarifa_manual_total,
        inclui=_inclui(args.inclui),
        adicional_kwh=args.adicional_kwh,
        adicional_tipo=args.adicional_tipo,
        projetar_ultima_tarifa=args.projetar_ultima_tarifa,
    )
    build_extras(tariff)
    if manual:
        parse_rate(args.tarifa_manual_total)
        return tariff
    if services.refresh is not None:
        services.refresh(RefreshRequest(args.permitir_cache_vencido))
    if args.municipio is not None:
        if services.supplier_source is None or services.store is None:
            raise UnavailableError("resolução de município indisponível neste ambiente")
        supplier = resolve_supplier(
            SupplierRequest(args.municipio, args.distribuidora, tty and not args.json, args.json),
            services.supplier_source,
            services.store,
            services.chooser,
        )
        tariff = dataclasses.replace(tariff, cnpj=supplier.distributor.cnpj)
    return tariff


def _dump(doc: dict[str, Any], out: TextIO, compact: bool = False) -> None:
    text = json.dumps(doc, ensure_ascii=False) if compact else json.dumps(doc, ensure_ascii=False, indent=2)
    _emit(text + "\n", out)


def _acompanhar(args: argparse.Namespace, services: Services, tty: bool, out: TextIO) -> None:
    sample = _seconds(args.intervalo, "--intervalo")
    persist = _seconds(args.persistir_a_cada, "--persistir-a-cada")
    power = parse_watts(args.potencia).value if args.potencia is not None else None
    tariff = _session_tariff(args, services, tty, required=True)
    assert tariff is not None
    request = TrackRequest(tariff, sample, persist, power, args.completar_com_potencia)
    zone = load_zone()
    rewriting = tty and not args.json
    dirty = False

    def on_render(view: TrackView) -> None:
        nonlocal dirty
        if args.json:
            _dump(json_schema.success_document(
                "sessao acompanhar", json_schema.session_tick_to_json(view, COST_LABEL)), out, True)
        elif rewriting:
            _emit("\r" + render_pt.render_tick(view, zone) + "\x1b[K", out)
            dirty = True
        else:
            _emit(render_pt.render_tick(view, zone) + "\n", out)
        out.flush()

    ledger = _need(services.session_ledger, "registro de sessões")
    meter_factory = _need(services.live_meter, "medidor ao vivo")
    try:
        result = track_session(
            request,
            tariff_source=services.tariff_source,
            meter=meter_factory(),
            ledger=ledger,
            clock=services.clock,
            mono=_need(services.mono, "relógio monotônico"),
            boot=_need(services.boot, "identificação de boot"),
            sleep=services.sleep or time.sleep,
            should_stop=services.should_stop or (lambda: False),
            on_render=on_render,
        )
    finally:
        if dirty:
            _emit("\n", out)
    if args.json:
        acc = result.acc
        final = TrackView(result.session.id, result.session.ended_at or result.session.last_seen_utc,
                          acc, None, acc.measured_wh / 1000, acc.assumed_wh / 1000, None)
        doc = json_schema.session_tick_to_json(
            final, COST_LABEL, final=True, end_reason=result.end_reason.value,
            warnings=result.warnings)
        _dump(json_schema.success_document("sessao acompanhar", doc), out, True)
    else:
        _emit(render_pt.render_track_end(result, zone), out)


def _sessao(args: argparse.Namespace, services: Services, tty: bool, out: TextIO) -> None:
    command = args.session_command
    if command == "acompanhar":
        _acompanhar(args, services, tty, out)
        return
    zone = load_zone()
    name = f"sessao {command}"
    if command == "listar":
        since, until = _aware(_parse_when(args.desde, "--desde")), _aware(_parse_when(args.ate, "--ate"))
        rows = list_sessions(_need(services.session_ledger, "registro de sessões"), since, until)
        if args.json:
            _dump(json_schema.success_document(
                name, json_schema.session_list_to_json(rows, COST_LABEL)), out)
        else:
            _emit(render_pt.render_session_list(rows, zone), out)
    elif command == "custo":
        since = _aware(_parse_when(args.desde, "--desde"))
        until = _aware(_parse_when(args.ate, "--ate")) or services.clock.now()
        assert since is not None
        if until <= since:
            raise DomainError("invalid_interval", "o fim do período deve ser posterior ao início")
        tariff = _session_tariff(args, services, tty, required=True)
        assert tariff is not None
        cost = period_cost(_need(services.session_ledger, "registro de sessões"),
                           tariff, services.tariff_source, since, until)
        if args.json:
            _dump(json_schema.success_document(name, json_schema.period_cost_to_json(cost)), out)
        else:
            _emit(render_pt.render_period_cost(cost), out)
    else:  # exportar
        if not re.fullmatch(r"[0-9]{1,18}", args.sessao_id):
            raise InvalidInput("o id da sessão deve ser um número inteiro")
        tariff = _session_tariff(args, services, tty, required=False)
        sid = int(args.sessao_id)
        outcome = export_summary(
            sid, _need(services.session_ledger, "registro de sessões"),
            _need(services.exporter, "exportador"), tariff, services.tariff_source)
        if args.json:
            _dump(json_schema.success_document(
                name, json_schema.export_to_json(sid, outcome, outcome.detail, COST_LABEL)), out)
        else:
            _emit(render_pt.render_export(outcome.detail, outcome), out)


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
    compact = False
    try:
        try:
            args = _build_parser().parse_args(list(argv))
        except SystemExit as exc:  # só `--help`
            return int(exc.code or 0)
        as_json = args.json
        if args.command == "sessao":
            compact = args.session_command == "acompanhar"
            _sessao(args, services, stdin_is_tty, out)
            return 0
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
            _dump(json_schema.domain_error_document(exc), out, compact)
        else:
            candidates = exc.candidates if isinstance(exc, SupplierAmbiguous) else ()
            _emit(render_pt.render_error(exc.code, exc.message, candidates), err)
        return exc.exit_code
