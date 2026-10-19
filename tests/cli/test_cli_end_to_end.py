"""CLI (etapa 15) com serviços injetados fake: D13, schema JSON v1, texto pt-BR."""

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pc_energy_cost.application.refresh_catalog import RefreshRequest, RefreshResult
from pc_energy_cost.domain.location_supplier.model import Municipality, SupplierLink
from pc_energy_cost.domain.metering.model import Available, Scope, Unavailable
from pc_energy_cost.domain.shared.errors import EXIT_CODES, DomainError, InsufficientCoverage
from pc_energy_cost.domain.tariff_catalog.model import Distributor
from pc_energy_cost.infrastructure.metering.csv_series import CsvPowerSeries
from pc_energy_cost.interface.cli.json_schema import SCHEMA_VERSION, validate
from pc_energy_cost.interface.cli.main import Services, run

from cli_fakes import CNPJ, FakeClock, FakeTariffSource

FIX = Path(__file__).parent.parent / "fixtures" / "metering"
SP = ZoneInfo("America/Sao_Paulo")
SP_IBGE = "3550308"
OTHER_CNPJ = "11111111000191"  # fictício

# tabela D13 fixada literalmente (os testes CLI a fixam)
D13 = {
    "invalid_input": 2, "ambiguous_decimal": 2, "invalid_interval": 2,
    "overlapping_intervals": 2, "timezone_data_missing": 2, "double_inclusion": 2,
    "inclusion_undeclared": 2, "csv_conflicting_duplicate": 2, "csv_unknown_columns": 2,
    "csv_invalid_header": 2, "csv_invalid_row": 2, "csv_too_many_rows": 2,
    "supplier_ambiguous": 3, "unsupported": 3, "tariff_ambiguous": 3,
    "tariff_not_found": 4, "tariff_not_in_effect": 4, "schema_mismatch": 4,
    "unexpected_html": 4, "download_incomplete": 4, "cache_corrupted": 4,
    "network_unavailable": 5, "unavailable": 6,
}


def _link(cnpj: str, sigla: str) -> SupplierLink:
    return SupplierLink(
        Municipality(SP_IBGE, "São Paulo", "SP"), Distributor(cnpj, sigla), "aneel:test", {}, "test"
    )


class FakeSuppliers:
    def __init__(self, links):
        self.links = links

    def official_links(self, ibge_code):
        return self.links

    def user_link(self, ibge_code):
        return None


class FakeStore:
    def __init__(self):
        self.saved = []

    def get_preference(self, key):
        return None

    def set_preference(self, key, value):
        pass

    def save_user_link(self, link):
        self.saved.append(link)


class ExplodingChooser:
    def choose(self, candidates):
        raise AssertionError("não deve perguntar")


class FirstChooser:
    def __init__(self):
        self.calls = 0

    def choose(self, candidates):
        self.calls += 1
        return candidates[0]


class FakeMeter:
    def __init__(self, availability=None, error=None):
        self._availability = availability or Available(Scope.CPU_PACKAGE)
        self._error = error

    def availability(self):
        return self._availability

    def read(self):
        if self._error:
            raise self._error
        return ()


def _services(**kw) -> Services:
    base = dict(
        tariff_source=FakeTariffSource(),
        clock=FakeClock(),
        supplier_source=FakeSuppliers([_link(CNPJ, "ELETROPAULO")]),
        store=FakeStore(),
        chooser=None,
        refresh=None,
        series_provider=lambda path: CsvPowerSeries(path),
        meter_provider=None,
    )
    base.update(kw)
    return Services(**base)


def _go(argv, capsys, services=None, tty=False):
    code = run(argv, services or _services(), tty)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def _json(argv, capsys, services=None, tty=False):
    code, out, err = _go([*argv, "--json"], capsys, services, tty)
    assert err == ""
    return code, json.loads(out)


MANUAL = ["estimar", "--potencia", "100", "--horas", "10", "--tarifa-manual-total", "0,78938"]


def test_text_output_pt_br_rounds_cost_and_labels_estimate(capsys):
    code, out, err = _go(MANUAL, capsys)
    assert code == 0 and err == ""
    assert "R$ 0,79" in out and "1,000 kWh" in out
    assert "estimativa da energia atribuível, não fatura" in out
    assert "manual" in out


def test_json_output_validates_against_schema_v1_with_string_money(capsys):
    code, doc = _json(MANUAL, capsys)
    assert code == 0
    assert doc["schema_version"] == SCHEMA_VERSION == "1"
    validate(doc)
    result = doc["result"]
    assert result["cost_brl"] == "0.79" and result["tarifa_base"] == "0.78938"
    assert isinstance(result["cost_brl"], str) and isinstance(result["taxa_total"], str)
    assert result["energy_kwh"] == "1.000" or Decimal(result["energy_kwh"]) == 1
    assert result["partial_data"] is False and result["scope"] == "manual"


def test_validator_rejects_malformed_documents(capsys):
    _, doc = _json(MANUAL, capsys)
    del doc["result"]["cost_brl"]
    with pytest.raises(ValueError):
        validate(doc)
    _, doc = _json(MANUAL, capsys)
    doc["result"]["cost_brl"] = 0.79  # dinheiro nunca é número
    with pytest.raises(ValueError):
        validate(doc)
    with pytest.raises(ValueError):
        validate({"schema_version": "2", "ok": True})


def test_manual_tariff_text_lists_inclusions_and_rate_composition(capsys):
    argv = ["estimar", "--potencia", "100", "--horas", "10", "--tarifa-manual-total", "0,80",
            "--inclui", "tributos", "--inclui", "bandeira"]
    code, out, _ = _go(argv, capsys)
    assert code == 0 and "R$ 0,80" in out
    assert "tributos" in out and "bandeira" in out
    assert "tarifa base" in out and "adicional" in out and "taxa total" in out
    _, doc = _json(argv, capsys)
    r = doc["result"]
    assert r["inclusoes_declaradas"] == ["tributos", "bandeira"]
    assert (r["tarifa_base"], r["adicional"], r["taxa_total"]) == ("0.80", "0", "0.80")


def test_manual_tariff_undeclared_inclusion_default_and_double_inclusion(capsys):
    code, doc = _json(MANUAL, capsys)
    assert doc["result"]["inclusoes_declaradas"] == ["nao-declarado"]
    argv = [*MANUAL[:-1], "0,80", "--inclui", "bandeira", "--adicional-kwh", "0,05",
            "--adicional-tipo", "bandeira"]
    code, doc = _json(argv, capsys)
    assert code == 2 and doc["error"]["code"] == "double_inclusion"
    argv = [*MANUAL[:-1], "0,80", "--adicional-kwh", "0,05", "--adicional-tipo", "outro"]
    code, doc = _json(argv, capsys)
    assert code == 2 and doc["error"]["code"] == "inclusion_undeclared"


def test_aneel_tariff_plus_additional_needs_no_inclui_and_says_base_excludes_taxes(capsys):
    argv = ["estimar", "--potencia", "1000", "--horas", "1", "--distribuidora", CNPJ,
            "--adicional-kwh", "0,05", "--adicional-tipo", "bandeira"]
    code, out, _ = _go(argv, capsys)
    assert code == 0, out
    assert "tributos" in out and "bandeiras" in out  # base não inclui tributos/bandeiras
    code, doc = _json(argv, capsys)
    validate(doc)
    r = doc["result"]
    assert r["taxa_total"] == "0.83938" and r["cost_brl"] == "0.84"
    assert r["inclusoes_declaradas"] == []
    assert r["provenance"] and r["provenance"][0]["reh"]


@pytest.mark.parametrize("code_name", sorted(D13))
def test_d13_exit_code_table(code_name, capsys):
    def boom(request):
        raise DomainError(code_name, "falha simulada")

    code, doc = _json(["atualizar-catalogo"], capsys, _services(refresh=boom))
    assert code == D13[code_name]
    assert doc["ok"] is False and doc["error"]["code"] == code_name
    validate(doc)


def test_d13_table_matches_domain_table():
    assert D13 == {k: v for k, v in EXIT_CODES.items()}


@pytest.mark.parametrize(
    "extra",
    [["--potencia=-1"], ["--potencia", "nan"], ["--potencia", "inf"], ["--potencia", "1e400"],
     ["--potencia", "100000,001"], ["--potencia", "1,2345"], ["--horas", "87600,0001"]],
)
def test_invalid_numeric_inputs_exit_2_with_error_code(extra, capsys):
    argv = ["estimar", "--potencia", "100", "--horas", "1", "--tarifa-manual-total", "0,8", *extra]
    argv = [a for a in argv]
    # a última ocorrência de cada opção vale no argparse
    code, doc = _json(argv, capsys)
    assert code == 2 and doc["error"]["code"] in ("invalid_input", "ambiguous_decimal")


def test_exact_limits_are_accepted(capsys):
    code, _ = _json(["estimar", "--potencia", "100000", "--horas", "87600",
                     "--tarifa-manual-total", "0,8"], capsys)
    assert code == 0


@pytest.mark.parametrize(
    "value,ok",
    [("0", True), ("100", True), ("=-0,10", False), ("100,000001", False), ("0,1234567", False)],
)
def test_manual_tariff_limits(value, ok, capsys):
    if value.startswith("="):
        argv = ["estimar", "--potencia", "100", "--horas", "1", f"--tarifa-manual-total{value}"]
    else:
        argv = ["estimar", "--potencia", "100", "--horas", "1", "--tarifa-manual-total", value]
    code, doc = _json(argv, capsys)
    if ok:
        assert code == 0
        if value == "0":
            assert "zero_rate" in doc["result"]["warnings"]
    else:
        assert code == 2 and doc["error"]["code"] == "invalid_input"


def test_negative_option_value_is_invalid_input_not_argparse_exit(capsys):
    # `-0,10` sem `=` é lido pelo argparse como opção: vira invalid_input, sem stderr do argparse
    code, out, err = _go(["estimar", "--potencia", "100", "--horas", "1",
                          "--tarifa-manual-total", "-0,10"], capsys)
    assert code == 2 and err.count("\n") <= 1 and "usage:" not in out + err
    assert "invalid_input" in err


def test_usage_errors_are_invalid_input_in_json_without_argparse_noise(capsys):
    for argv in (["estimar", "--nao-existe"], ["nada"], []):
        code, out, err = _go([*argv, "--json"], capsys)
        doc = json.loads(out)
        assert code == 2 and doc["error"]["code"] == "invalid_input" and err == ""
        validate(doc)


def test_help_exits_zero(capsys):
    code, out, err = _go(["--help"], capsys)
    assert code == 0 and "estimar" in out
    code, out, _ = _go(["estimar", "--help"], capsys)
    assert code == 0 and "--potencia" in out


def test_csv_series_without_enough_gap_is_insufficient_coverage_exit_2(tmp_path, capsys):
    hourly = tmp_path / "horaria.csv"
    hourly.write_text(
        "timestamp,watts\n2026-10-19T10:00:00,100\n2026-10-19T11:00:00,100\n"
        "2026-10-19T12:00:00,100\n", encoding="utf-8")
    argv = ["estimar", "--serie-csv", str(hourly), "--tarifa-manual-total", "0,8"]
    code, doc = _json(argv, capsys)
    assert code == 2 and doc["error"]["code"] == "insufficient_coverage"
    code, doc = _json([*argv, "--max-gap", "1h"], capsys)
    assert code == 0 and doc["result"]["cost_brl"] is not None


def test_partial_series_reports_coverage_and_excluded_intervals(capsys):
    argv = ["estimar", "--serie-csv", str(FIX / "serie_gap.csv"), "--tarifa-manual-total", "0,8"]
    code, doc = _json(argv, capsys)
    validate(doc)
    r = doc["result"]
    assert code == 0 and r["partial_data"] is True and "partial_data" in r["warnings"]
    assert Decimal(r["excluded_duration"]) > 0 and r["excluded_intervals"]
    assert Decimal(r["coverage_duration"]) + Decimal(r["excluded_duration"]) == Decimal(
        r["requested_duration"])
    code, out, _ = _go(argv, capsys)
    assert "dados parciais" in out and "cobertura" in out and "excluído" in out


def test_counter_insufficient_coverage_exits_6(capsys):
    meter = FakeMeter(error=InsufficientCoverage("sem cobertura", "counter"))
    code, doc = _json(["estimar", "--tarifa-manual-total", "0,8"], capsys,
                      _services(meter_provider=lambda max_watts: meter))
    assert code == 6 and doc["error"]["code"] == "insufficient_coverage"


def test_unavailable_meter_exits_6_and_missing_meter_too(capsys):
    meter = FakeMeter(Unavailable("permission_denied"))
    argv = ["estimar", "--tarifa-manual-total", "0,8", "--rapl-max-watts", "500"]
    code, doc = _json(argv, capsys, _services(meter_provider=lambda max_watts: meter))
    assert code == 6 and doc["error"]["code"] == "unavailable"
    assert "permission_denied" in doc["error"]["message"]
    code, doc = _json(argv, capsys, _services(meter_provider=None))
    assert code == 6 and doc["error"]["code"] == "unavailable"


def test_rapl_max_watts_is_range_checked(capsys):
    code, doc = _json(["estimar", "--tarifa-manual-total", "0,8", "--rapl-max-watts", "10001"],
                      capsys)
    assert code == 2 and doc["error"]["code"] == "invalid_input"


def test_ambiguity_with_json_never_prompts_and_lists_candidates(capsys):
    suppliers = FakeSuppliers([_link(CNPJ, "ELETROPAULO"), _link(OTHER_CNPJ, "CERIS")])
    svc = _services(supplier_source=suppliers, chooser=ExplodingChooser())
    argv = ["estimar", "--potencia", "100", "--horas", "1", "--municipio", SP_IBGE]
    code, doc = _json(argv, capsys, svc, tty=True)
    assert code == 3 and doc["error"]["code"] == "supplier_ambiguous"
    cnpjs = [c["cnpj"] for c in doc["error"]["candidates"]]
    assert cnpjs == [CNPJ, OTHER_CNPJ]
    validate(doc)
    code, out, err = _go(argv, capsys, svc, tty=False)  # sem TTY e sem --json: também não pergunta
    assert code == 3 and "supplier_ambiguous" in err and CNPJ in err and OTHER_CNPJ in err


def test_ambiguity_in_tty_text_mode_uses_chooser_and_distribuidora_flag_resolves(capsys):
    suppliers = FakeSuppliers([_link(CNPJ, "ELETROPAULO"), _link(OTHER_CNPJ, "CERIS")])
    chooser = FirstChooser()
    store = FakeStore()
    svc = _services(supplier_source=suppliers, chooser=chooser, store=store)
    argv = ["estimar", "--potencia", "100", "--horas", "1", "--municipio", SP_IBGE]
    code, out, _ = _go(argv, capsys, svc, tty=True)
    assert code == 0 and chooser.calls == 1 and "ELETROPAULO" in out
    code, doc = _json([*argv, "--distribuidora", CNPJ], capsys, svc)
    assert code == 0 and doc["result"]["supplier"]["cnpj"] == CNPJ and chooser.calls == 1


def test_future_date_needs_projection_flag_and_emits_projected_tariff(capsys):
    base = ["estimar", "--potencia", "100", "--horas", "1", "--distribuidora", CNPJ,
            "--inicio", "2035-01-01T10:00:00"]
    code, doc = _json(base, capsys)
    assert code == 4 and doc["error"]["code"] == "tariff_not_in_effect"
    code, doc = _json([*base, "--projetar-ultima-tarifa"], capsys)
    assert code == 0 and "projected_tariff" in doc["result"]["warnings"]
    code, out, _ = _go([*base, "--projetar-ultima-tarifa"], capsys)
    assert "projetada" in out


def test_nominal_scenario_is_labelled_scenario(capsys):
    code, doc = _json(["estimar", "--cenario-potencia-nominal", "650", "--horas", "1",
                       "--tarifa-manual-total", "0,8"], capsys)
    assert code == 0 and doc["result"]["scope"] == "scenario"
    code, out, _ = _go(["estimar", "--cenario-potencia-nominal", "650", "--horas", "1",
                        "--tarifa-manual-total", "0,8"], capsys)
    assert "cenário" in out


def _refresh(stale: bool):
    def refresh(request: RefreshRequest) -> RefreshResult:
        assert request.permitir_cache_vencido is True
        return RefreshResult(
            refreshed=not stale, stale=stale, age=timedelta(hours=30),
            vigencia=(date(2025, 7, 4), date(2026, 7, 3)), tariffs_loaded=None,
        )

    return refresh


def test_stale_catalog_shows_age_and_vigencia_in_text_and_json(capsys):
    svc = _services(refresh=_refresh(True))
    code, out, _ = _go(["atualizar-catalogo", "--permitir-cache-vencido"], capsys, svc)
    assert code == 0
    assert "30 h" in out and "04/07/2025" in out and "03/07/2026" in out
    assert "vencido" in out and "parcial / indicativo" in out
    code, doc = _json(["atualizar-catalogo", "--permitir-cache-vencido"], capsys, svc)
    validate(doc)
    r = doc["result"]
    assert r["stale"] is True and r["age_seconds"] == "108000"
    assert r["vigencia"] == {"inicio": "2025-07-04", "fim": "2026-07-03"}


def test_estimar_with_aneel_tariff_reports_catalog_state(capsys):
    svc = _services(refresh=_refresh(True))
    code, doc = _json(["estimar", "--potencia", "100", "--horas", "1", "--distribuidora", CNPJ,
                       "--permitir-cache-vencido"], capsys, svc)
    assert code == 0 and doc["result"]["catalog"]["stale"] is True
    validate(doc)


def test_estimate_inicio_fim_window(capsys):
    code, doc = _json(["estimar", "--potencia", "1000", "--inicio", "2026-10-19T10:00:00",
                       "--fim", "2026-10-19T12:00:00", "--tarifa-manual-total", "0,5"], capsys)
    assert code == 0 and doc["result"]["cost_brl"] == "1.00"
    code, doc = _json(["estimar", "--potencia", "1000", "--inicio", "ontem",
                       "--fim", "2026-10-19T12:00:00", "--tarifa-manual-total", "0,5"], capsys)
    assert code == 2 and doc["error"]["code"] == "invalid_input"


# -- composição real (etapa 16): store SQLite temporário e fontes FAKE (mocks, não live) ----------
import hashlib  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

from pc_energy_cost import composition  # noqa: E402
from pc_energy_cost.__main__ import main as entry_main  # noqa: E402
from pc_energy_cost.infrastructure.http.fetcher import DownloadResult  # noqa: E402
from pc_energy_cost.infrastructure.persistence.sqlite_store import SqliteStore  # noqa: E402

ANEEL = Path(__file__).parent.parent / "fixtures" / "aneel"
REPO = Path(__file__).resolve().parents[2]
_PACKAGES = {
    "tarifas-distribuidoras-energia-eletrica": "package_show_tarifas.json",
    "indqual-municipio": "package_show_indqual.json",
    "indicadores-coletivos-de-continuidade-dec-e-fec": "package_show_decfec.json",
}
_CSVS = {
    "tarifas-homologadas-distribuidoras-energia-eletrica.csv": "tarifas_eletropaulo.csv",
    "indqual-municipio.csv": "indqual_capital.csv",
    "indicadores-continuidade-coletivos-limite.csv": "limite_recorte.csv",
}


def _fake_json(url):
    return (ANEEL / _PACKAGES[url.split("id=")[1]]).read_bytes()


def _fake_download(url, part):
    part.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ANEEL / _CSVS[url.rsplit("/", 1)[1]], part)
    data = part.read_bytes()
    return DownloadResult(part, hashlib.sha256(data).hexdigest(), len(data), "Sun, 18 Oct 2026 12:00:00 GMT")


def _no_network(*args):
    raise AssertionError("a composição não deve usar a rede neste teste")


def _real(tmp_path, **kw):
    kw.setdefault("fetch_json", _fake_json)
    kw.setdefault("download", _fake_download)
    kw.setdefault("clock", FakeClock())
    return composition.build_services(db_path=tmp_path / "store.sqlite", **kw)


def test_a48_estimar_via_composicao_real_text_and_json(tmp_path, capsys):
    services = _real(tmp_path, fetch_json=_no_network, download=_no_network)
    code, out, err = _go(MANUAL, capsys, services)
    assert code == 0 and err == ""
    assert "R$ 0,79" in out and "1,000 kWh" in out
    code, doc = _json(MANUAL, capsys, services)
    assert code == 0 and doc["schema_version"] == "1"
    validate(doc)
    assert doc["result"]["cost_brl"] == "0.79"


def test_atualizar_catalogo_via_composicao_grava_no_store_e_estimar_usa_tarifa_aneel(
    tmp_path, capsys
):
    services = _real(tmp_path)
    code, doc = _json(["atualizar-catalogo"], capsys, services)
    assert code == 0 and doc["ok"] is True
    validate(doc)
    store = SqliteStore(tmp_path / "store.sqlite")
    assert store.tariff_records(CNPJ) and store.official_links(SP_IBGE)
    assert store.source_info().last_modified == "Sun, 18 Oct 2026 12:00:00 GMT"
    store.close()
    argv = ["estimar", "--potencia", "1000", "--horas", "1", "--municipio", SP_IBGE,
            "--distribuidora", CNPJ]
    offline = _real(tmp_path, fetch_json=_no_network, download=_no_network)
    code, doc = _json(argv, capsys, offline)
    assert code == 0, doc
    assert doc["result"]["cost_brl"] == "0.79"  # cache fresco: sem rede


def test_default_db_path_env_argument_and_never_inside_repo(tmp_path, monkeypatch):
    explicit = tmp_path / "x.sqlite"
    assert composition.resolve_db_path(explicit, {"PC_ENERGY_COST_DB": "/ignorado"}) == explicit
    assert composition.resolve_db_path(None, {"PC_ENERGY_COST_DB": str(explicit)}) == explicit
    linux = composition.default_db_path({"XDG_DATA_HOME": str(tmp_path)}, "linux", tmp_path / "h")
    assert linux == tmp_path / "pc-energy-cost" / "store.sqlite"
    home = composition.default_db_path({}, "linux", tmp_path / "h")
    assert home == tmp_path / "h" / ".local" / "share" / "pc-energy-cost" / "store.sqlite"
    win = composition.default_db_path({"LOCALAPPDATA": str(tmp_path)}, "win32", tmp_path / "h")
    assert win == tmp_path / "pc-energy-cost" / "store.sqlite"
    mac = composition.default_db_path({}, "darwin", tmp_path / "h")
    assert mac.parts[-3:] == ("Application Support", "pc-energy-cost", "store.sqlite") or (
        mac.parts[-2:] == ("pc-energy-cost", "store.sqlite")
    )
    for path in (linux, home, win, mac):
        assert REPO not in path.parents


def test_store_is_lazy_building_services_does_not_touch_disk(tmp_path):
    db = tmp_path / "sub" / "store.sqlite"
    composition.build_services(db_path=db)
    assert not db.exists() and not db.parent.exists()


def test_main_returns_int_exit_code_and_honours_env_store(tmp_path, capsys):
    env = {"PC_ENERGY_COST_DB": str(tmp_path / "e.sqlite")}
    code = entry_main(MANUAL, env=env)
    out = capsys.readouterr().out
    assert code == 0 and isinstance(code, int) and "R$ 0,79" in out
    assert entry_main(["estimar", "--potencia=-1", "--horas", "1", "--tarifa-manual-total", "0,8"], env=env) == 2
    capsys.readouterr()
    before = sorted(p.name for p in tmp_path.iterdir())
    assert entry_main(["--help"], env=env) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def _minimal_env(tmp_path):
    """Ambiente mínimo e isolado; no Windows o Python exige SYSTEMROOT para iniciar."""
    env = {"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin",
           "PC_ENERGY_COST_DB": str(tmp_path / "s.sqlite")}
    if "SYSTEMROOT" in os.environ:
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return env


def test_python_dash_m_help_exits_zero(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "pc_energy_cost", "--help"],
        capture_output=True, text=True, cwd=REPO, timeout=60,
        env=_minimal_env(tmp_path),
    )
    assert result.returncode == 0 and "pc-energy-cost" in result.stdout
    assert list(tmp_path.iterdir()) == []  # --help não cria store nem cache


def test_console_script_semantics_sys_exit_of_main_return_value(tmp_path):
    code = "import sys; from pc_energy_cost.__main__ import main; sys.exit(main(['estimar', '--potencia=-1', '--horas', '1', '--tarifa-manual-total', '0,8']))"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO, timeout=60,
        env=_minimal_env(tmp_path),
    )
    assert result.returncode == 2  # uso inválido ⇒ invalid_input


# -- telemetria RAPL pela composição (sysfs FAKE; sem hardware) -----------------------------
SEC = 1_000_000_000


class _RaplHarness:
    def __init__(self, tmp_path, steps):
        self.root = tmp_path / "powercap"
        shutil.copytree(Path(__file__).parent.parent / "fixtures" / "metering" / "powercap_fake",
                        self.root)
        self.mono = 5 * SEC
        self.wall = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)
        self.counter = 0
        self.steps = list(steps)  # (segundos, microjoules) por sleep

    def sleep(self, requested):
        seconds, uj = self.steps.pop(0)
        self.mono += int(seconds * SEC)
        self.wall += timedelta(seconds=seconds)
        self.counter += uj
        (self.root / "intel-rapl:0" / "energy_uj").write_text(f"{self.counter}\n")

    def services(self, tmp_path):
        return _real(
            tmp_path, rapl_root=self.root, sleep=self.sleep,
            monotonic_ns=lambda: self.mono, wall_clock=lambda: self.wall,
        )


def test_rapl_via_composition_samples_in_read_and_reports_cpu_package(tmp_path, capsys):
    h = _RaplHarness(tmp_path, [(5, 50_000_000), (5, 50_000_000)])
    argv = ["estimar", "--tarifa-manual-total", "0,78938"]
    code, doc = _json(argv, capsys, h.services(tmp_path))
    assert code == 0, doc
    r = doc["result"]
    assert r["scope"] == "cpu_package" and r["partial_data"] is False
    assert Decimal(r["energy_kwh"]) > 0


def test_rapl_excluded_intervals_reach_the_estimate_as_partial_data(tmp_path, capsys):
    # segundo par com dt = 20 s > dt_max (5 s): indeterminate_wrap ⇒ excluído, vira partial_data
    h = _RaplHarness(tmp_path, [(5, 50_000_000), (20, 50_000_000)])
    argv = ["estimar", "--tarifa-manual-total", "0,78938"]
    code, doc = _json(argv, capsys, h.services(tmp_path))
    assert code == 0, doc
    r = doc["result"]
    assert r["partial_data"] is True
    assert any(e["reason"] == "indeterminate_wrap" for e in r["excluded_intervals"])


def test_rapl_all_excluded_is_exit_6_and_unavailable_is_exit_6(tmp_path, capsys):
    h = _RaplHarness(tmp_path, [(20, 1), (20, 1)])
    argv = ["estimar", "--tarifa-manual-total", "0,78938"]
    code, doc = _json(argv, capsys, h.services(tmp_path))
    assert code == 6 and doc["error"]["code"] == "insufficient_coverage"
    code, doc = _json(argv, capsys, _real(tmp_path, rapl_root=tmp_path / "nao_existe"))
    assert code == 6 and doc["error"]["code"] == "unavailable"


def test_rapl_max_watts_non_integer_is_invalid_input(tmp_path, capsys):
    h = _RaplHarness(tmp_path, [])
    argv = ["estimar", "--tarifa-manual-total", "0,8", "--rapl-max-watts", "10,5"]
    code, doc = _json(argv, capsys, h.services(tmp_path))
    assert code == 2 and doc["error"]["code"] == "invalid_input"
