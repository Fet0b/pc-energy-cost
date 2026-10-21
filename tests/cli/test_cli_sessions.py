"""S14: CLI `sessao` ponta a ponta com relógios, sensor, ledger e exportador fakes."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from cli_fakes import FakeTariffSource
from session_fakes import FakeBoot, FakeExporter, FakeLedger, FakeMeter, World

from pc_energy_cost import composition
from pc_energy_cost.__main__ import main as entry_main
from pc_energy_cost.domain.shared.errors import EXIT_CODES
from pc_energy_cost.domain.usage_session.model import Accumulator, EndReason, EnergyBasis, Session
from pc_energy_cost.domain.metering.model import Scope
from pc_energy_cost.infrastructure.export.proxmox_text import ProxmoxCompatibleTextExporter
from pc_energy_cost.interface.cli import json_schema
from pc_energy_cost.interface.cli.main import Services, run

TARIFF = ["--tarifa-manual-total", "0,80", "--inclui", "tributos"]


def _services(world=None, ledger=None, ticks=3, **kw) -> Services:
    world = world or World()
    ledger = ledger if ledger is not None else FakeLedger()
    base = dict(
        tariff_source=FakeTariffSource(),
        clock=world,
        session_ledger=ledger,
        live_meter=lambda: FakeMeter(world, power_w="360"),
        mono=world,
        boot=FakeBoot(),
        exporter=ProxmoxCompatibleTextExporter(),
        sleep=world.sleep,
        should_stop=lambda: world.sleeps >= ticks,
    )
    base.update(kw)
    return Services(**base)


def _go(argv, capsys, services):
    code = run(argv, services, False)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def _seed_closed(ledger, world, sid_hours=1):
    start = world.wall
    s = Session(1, start, start + timedelta(hours=sid_hours), start + timedelta(hours=sid_hours),
                EndReason.USER_STOP, "b", 5, 60, Scope.CPU_PACKAGE, EnergyBasis.MEASURED_COUNTER)
    ledger.seed(s, Accumulator(measured_wh=Decimal("1000"), covered_s=Decimal(3600)))


def test_s14_acompanhar_text_is_append_only_when_not_tty_and_closes_session(capsys):
    world, ledger = World(), FakeLedger()
    svc = _services(world, ledger, ticks=3)
    code, out, err = _go(["sessao", "acompanhar", "--intervalo", "5", *TARIFF], capsys, svc)
    assert code == 0 and err == ""
    assert "\r" not in out
    assert out.count("sessão 1") >= 3
    assert "estimativa da energia atribuível, não fatura" in out
    assert ledger.sessions[1].end_reason is EndReason.USER_STOP


def test_s14_acompanhar_json_emits_one_valid_object_per_update(capsys):
    svc = _services(ticks=3)
    code, out, err = _go(["sessao", "acompanhar", "--intervalo", "5", *TARIFF, "--json"], capsys, svc)
    assert code == 0 and err == ""
    docs = [json.loads(line) for line in out.splitlines()]
    assert len(docs) >= 4  # 3 atualizações + linha final
    for doc in docs:
        json_schema.validate(doc)
        assert doc["ok"] is True and doc["command"] == "sessao acompanhar"
    assert [d["result"]["final"] for d in docs] == [False] * (len(docs) - 1) + [True]
    assert docs[-1]["result"]["end_reason"] == "user_stop"
    assert Decimal(docs[-1]["result"]["measured_kwh"]) > 0


def test_s14_acompanhar_stale_meter_prints_sem_leitura(capsys):
    world = World()
    svc = _services(world, ticks=8, live_meter=lambda: FakeMeter(world, silent=range(1, 100)))
    code, out, _ = _go(["sessao", "acompanhar", "--intervalo", "1", *TARIFF], capsys, svc)
    assert code == 0 and "sem leitura (obsoleta há" in out


def test_s14_acompanhar_tty_rewrites_line(capsys):
    world = World()
    svc = _services(world, ticks=2)
    code = run(["sessao", "acompanhar", "--intervalo", "5", *TARIFF], svc, True)
    out = capsys.readouterr().out
    assert code == 0 and out.count("\r") >= 2 and out.endswith("\n")


def test_s14_acompanhar_unavailable_meter_exit_6_without_session(capsys):
    world, ledger = World(), FakeLedger()
    svc = _services(world, ledger, live_meter=lambda: FakeMeter(world, available=False))
    code, out, err = _go(["sessao", "acompanhar", *TARIFF], capsys, svc)
    assert code == EXIT_CODES["unavailable"] == 6 and "unavailable" in err
    assert ledger.sessions == {}


def test_s14_acompanhar_with_manual_power_does_not_need_sensor(capsys):
    world, ledger = World(), FakeLedger()
    svc = _services(world, ledger, live_meter=lambda: FakeMeter(world, available=False))
    code, out, _ = _go(["sessao", "acompanhar", "--potencia", "100", "--intervalo", "5", *TARIFF],
                       capsys, svc)
    assert code == 0 and ledger.sessions[1].energy_basis is EnergyBasis.USER_POWER


def test_s14_acompanhar_open_live_session_is_session_already_open(capsys):
    world, ledger = World(), FakeLedger()
    ledger.seed(Session(1, world.wall, world.wall, None, None, "boot-1", 5, 60,
                        Scope.CPU_PACKAGE, EnergyBasis.MEASURED_COUNTER))
    code, doc = None, None
    code, out, _ = _go(["sessao", "acompanhar", *TARIFF, "--json"], capsys, _services(world, ledger))
    assert len(out.splitlines()) == 1  # NDJSON: o erro também é uma linha só
    doc = json.loads(out)
    json_schema.validate(doc)
    assert code == EXIT_CODES["session_already_open"] == 2
    assert doc["error"]["code"] == "session_already_open"


@pytest.mark.parametrize("argv", [
    ["sessao"], ["sessao", "acompanhar", "--intervalo", "abc"],
    ["sessao", "acompanhar", "--bogus"], ["sessao", "exportar"],
    ["sessao", "acompanhar", "--intervalo", "0"],
    ["sessao", "acompanhar", "--completar-com-potencia"],
])
def test_s14_usage_errors_are_invalid_input_exit_2(argv, capsys):
    code, out, err = _go([*argv, *TARIFF], capsys, _services())
    assert code == 2 and "invalid_input" in err


def test_s14_listar_text_and_json(capsys):
    world, ledger = World(), FakeLedger()
    _seed_closed(ledger, world)
    code, out, err = _go(["sessao", "listar"], capsys, _services(world, ledger))
    assert code == 0 and err == "" and "1,000 kWh" in out and "user_stop" in out
    code, out, _ = _go(["sessao", "listar", "--json"], capsys, _services(world, ledger))
    doc = json.loads(out)
    json_schema.validate(doc)
    assert doc["command"] == "sessao listar" and doc["result"]["sessions"][0]["id"] == 1
    assert doc["result"]["sessions"][0]["measured_kwh"] == "1"


def test_s14_listar_empty(capsys):
    code, out, _ = _go(["sessao", "listar"], capsys, _services())
    assert code == 0 and "Nenhuma sessão" in out


def test_s14_custo_text_and_json(capsys):
    world, ledger = World(), FakeLedger()
    _seed_closed(ledger, world)
    argv = ["sessao", "custo", "--desde", "2026-10-21T00:00:00+00:00",
            "--ate", "2026-10-22T00:00:00+00:00", *TARIFF]
    code, out, err = _go(argv, capsys, _services(world, ledger))
    assert code == 0 and "R$ 0,80" in out and "estimativa da energia atribuível, não fatura" in out
    code, out, _ = _go([*argv, "--json"], capsys, _services(world, ledger))
    doc = json.loads(out)
    json_schema.validate(doc)
    r = doc["result"]
    assert doc["command"] == "sessao custo"
    assert r["cost_brl"] == "0.80" and r["measured_cost_brl"] == "0.80" and r["assumed_cost_brl"] == "0.00"


def test_s14_custo_invalid_interval_exit_2(capsys):
    argv = ["sessao", "custo", "--desde", "2026-10-22T00:00:00", "--ate", "2026-10-21T00:00:00", *TARIFF]
    code, _, err = _go(argv, capsys, _services())
    assert code == 2 and "invalid_interval" in err


def test_s14_exportar_text_and_json(capsys):
    world, ledger = World(), FakeLedger()
    _seed_closed(ledger, world)
    code, out, err = _go(["sessao", "exportar", "1", *TARIFF], capsys, _services(world, ledger))
    assert code == 0 and "Proxmox-compatível (texto)" in out and "R$ 0,80" in out
    code, out, _ = _go(["sessao", "exportar", "1", *TARIFF, "--json"], capsys, _services(world, ledger))
    doc = json.loads(out)
    json_schema.validate(doc)
    assert doc["command"] == "sessao exportar"
    assert doc["result"]["truncated"] is False and "Energia medida" in doc["result"]["text"]


def test_s14_exportar_not_found_exit_2(capsys):
    code, out, err = _go(["sessao", "exportar", "99"], capsys, _services())
    assert code == EXIT_CODES["session_not_found"] and "session_not_found" in err
    code, out, _ = _go(["sessao", "exportar", "99", "--json"], capsys, _services())
    json_schema.validate(json.loads(out))


def test_s14_exportar_non_integer_id_is_invalid_input(capsys):
    code, _, err = _go(["sessao", "exportar", "x"], capsys, _services())
    assert code == 2 and "invalid_input" in err


def test_s14_session_json_schema_rejects_wrong_command_and_shape():
    doc = {"schema_version": "1", "ok": True, "command": "sessao listar", "result": {"foo": 1}}
    with pytest.raises(ValueError):
        json_schema.validate(doc)
    doc = {"schema_version": "1", "ok": True, "command": "sessao inventado",
           "result": {"label": "x", "sessions": []}}
    with pytest.raises(ValueError):
        json_schema.validate(doc)


# -- sem arquivos criados fora de subcomandos que precisam do ledger ---------------------------
def test_s14_help_usage_error_and_manual_estimate_create_no_sqlite_files(tmp_path):
    env = {"PC_ENERGY_COST_DB": str(tmp_path / "store.sqlite")}
    for argv in (
        ["--help"], ["sessao", "--help"], ["sessao", "acompanhar", "--help"],
        ["sessao", "acompanhar", "--intervalo", "abc", *TARIFF],
        ["sessao", "exportar", "x"],
        ["estimar", "--potencia", "100", "--horas", "1", "--tarifa-manual-total", "0,8"],
    ):
        entry_main(argv, env=env)
    assert list(tmp_path.iterdir()) == []


def test_s14_building_services_is_lazy_and_listar_creates_only_sessions_ledger(tmp_path, capsys):
    db = tmp_path / "d" / "store.sqlite"
    composition.build_services(db_path=db)
    assert not db.parent.exists()
    assert entry_main(["sessao", "listar"], env={"PC_ENERGY_COST_DB": str(db)}) == 0
    capsys.readouterr()
    names = sorted(p.name for p in db.parent.iterdir())
    assert "sessions.sqlite" in names and "store.sqlite" not in names


def test_s14_composition_wires_real_sessions_end_to_end_in_tmp(tmp_path, capsys):
    world = World()
    db = tmp_path / "store.sqlite"
    svc = composition.build_services(
        db_path=db, clock=world, monotonic_ns=world.monotonic_ns, sleep=world.sleep,
        session_meter=lambda: FakeMeter(world, power_w="360"),
        should_stop=lambda: world.sleeps >= 2,
    )
    code, out, err = _go(["sessao", "acompanhar", "--intervalo", "5", *TARIFF], capsys, svc)
    assert code == 0, err
    code, out, _ = _go(["sessao", "listar", "--json"], capsys, svc)
    doc = json.loads(out)
    json_schema.validate(doc)
    assert len(doc["result"]["sessions"]) == 1
    assert not db.exists()  # o store.sqlite nunca é aberto por sessões
