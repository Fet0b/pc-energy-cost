"""S12: contrato das portas de sessão (SummaryExporter, SessionLedger, LiveMeter).

Nada aqui fala com Proxmox, rede ou credencial; o SQLite fica em `tmp_path`.
"""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from session_fakes import FakeExporter, FakeLedger  # noqa: E402  (pythonpath no pyproject)

from pc_energy_cost.domain.metering.model import Available, Scope, Unavailable  # noqa: E402
from pc_energy_cost.domain.usage_session.model import (  # noqa: E402
    Accumulator,
    EndReason,
    EnergyBasis,
    ExportOutcome,
    Session,
    SessionCostSummary,
)
from pc_energy_cost.infrastructure.export.proxmox_text import (  # noqa: E402
    ProxmoxCompatibleTextExporter,
)
from pc_energy_cost.infrastructure.metering.live_manual import LiveManualPower  # noqa: E402
from pc_energy_cost.infrastructure.metering.live_rapl import LiveRaplMeter  # noqa: E402
from pc_energy_cost.infrastructure.metering.live_wmi import LiveWmiMeter  # noqa: E402
from pc_energy_cost.infrastructure.persistence.sqlite_sessions import (  # noqa: E402
    SqliteSessionLedger,
)

SEC = 1_000_000_000
T0 = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
WMI_OK = {
    "MeterType": 0, "BaseUnits": 7, "UnitModifier": -3, "CurrentReading": 100000,
    "Status": "OK", "SupportCapabilities": 0, "SamplingPeriod": 1000,
}


# ------------------------------------------------------------------ exportador
def _summary():
    return SessionCostSummary(
        session_id=1, started_at=T0, ended_at=T0 + timedelta(hours=1),
        measured_energy_kwh=Decimal("0.5"), assumed_energy_kwh=Decimal(0),
        covered_s=Decimal(3600), excluded_s=Decimal(0), partial_data=False,
        scope=Scope.CPU_PACKAGE, energy_basis=EnergyBasis.MEASURED_COUNTER,
    )


@pytest.mark.parametrize("make", [FakeExporter, ProxmoxCompatibleTextExporter],
                         ids=["fake", "proxmox-texto"])
def test_s12_exporter_contract(make):
    summary = _summary()
    outcome = make().export(summary)
    assert isinstance(outcome, ExportOutcome)
    assert isinstance(outcome.truncated, bool) and isinstance(outcome.delivered, bool)
    assert summary == _summary()  # o resumo não é alterado


# ------------------------------------------------------------------ ledger
@pytest.fixture(params=["sqlite", "fake"])
def ledger(request, tmp_path):
    if request.param == "fake":
        yield FakeLedger()
        return
    led = SqliteSessionLedger(tmp_path / "sessions.sqlite")
    yield led
    led.close_connection()


def _open(ledger, at=T0):
    return ledger.open_session(
        started_at=at, boot_id="b", sample_interval_s=5, persist_interval_s=60,
        scope=Scope.CPU_PACKAGE, energy_basis=EnergyBasis.MEASURED_COUNTER,
    )


def test_s12_ledger_open_heartbeat_close_get(ledger):
    s = _open(ledger)
    assert isinstance(s, Session) and s.is_open
    acc = Accumulator(measured_wh=Decimal("1.5"), covered_s=Decimal(30))
    ledger.heartbeat(s.id, T0 + timedelta(seconds=30), acc)
    got, got_acc = ledger.get(s.id)
    assert got.is_open and got_acc.measured_wh == Decimal("1.5")
    closed = ledger.close(s.id, T0 + timedelta(seconds=40), EndReason.USER_STOP, acc)
    assert closed.end_reason is EndReason.USER_STOP and not closed.is_open
    assert ledger.get(s.id)[0].ended_at == T0 + timedelta(seconds=40)
    assert [x.id for x, _ in ledger.list_sessions()] == [s.id]


def test_s12_ledger_unknown_and_empty(ledger):
    assert ledger.get(999) is None
    assert ledger.recover_open(lambda s: pytest.fail("não deve decidir")) is None
    assert list(ledger.list_sessions()) == []


def test_s12_ledger_zero_accumulator_stays_zero_not_missing(ledger):
    s = _open(ledger)
    ledger.close(s.id, T0 + timedelta(seconds=1), EndReason.USER_STOP, Accumulator())
    assert ledger.get(s.id)[1] == Accumulator()


# ------------------------------------------------------------------ medidores
class _Clk:
    def __init__(self):
        self.mono, self.wall = 5 * SEC, T0

    def advance(self, s):
        self.mono += int(s * SEC)
        self.wall += timedelta(seconds=s)

    def monotonic_ns(self):
        return self.mono


class _Env:
    def __init__(self, tmp_path, copier):
        self.tmp_path, self.copier, self.clk = tmp_path, copier, _Clk()
        self.root = None
        self.wmi_payload = WMI_OK


def _rapl(env):
    env.root = env.copier(env.tmp_path / "powercap")
    return LiveRaplMeter(env.root, monotonic_ns=lambda: env.clk.mono, wall_clock=lambda: env.clk.wall)


def _rapl_missing(env):
    return LiveRaplMeter(env.tmp_path / "nao_existe", monotonic_ns=lambda: env.clk.mono,
                         wall_clock=lambda: env.clk.wall)


def _wmi(env):
    def runner(argv, timeout):
        return 0, json.dumps(env.wmi_payload) if env.wmi_payload else ""
    return LiveWmiMeter(runner=runner, monotonic_ns=lambda: env.clk.mono,
                        wall_clock=lambda: env.clk.wall)


def _wmi_missing(env):
    env.wmi_payload = None
    return _wmi(env)


def _manual(env):
    return LiveManualPower(Decimal(100), env.clk)


AVAILABLE = [
    pytest.param(_rapl, Scope.CPU_PACKAGE, EnergyBasis.MEASURED_COUNTER, id="rapl-fake"),
    pytest.param(_wmi, Scope.COMPONENT, EnergyBasis.MEASURED_POWER, id="wmi-fake"),
    pytest.param(_manual, Scope.MANUAL, EnergyBasis.USER_POWER, id="manual"),
]
UNAVAILABLE = [
    pytest.param(_rapl_missing, id="rapl-ausente"),
    pytest.param(_wmi_missing, id="wmi-ausente"),
]


@pytest.fixture
def env(tmp_path, copy_powercap_fake):
    return _Env(tmp_path, copy_powercap_fake)


@pytest.mark.parametrize(("make", "scope", "basis"), AVAILABLE)
def test_s12_meter_available_contract(make, scope, basis, env):
    m = make(env)
    avail = m.availability()
    assert isinstance(avail, Available) and avail.scope is scope
    assert m.energy_basis() is basis
    assert m.max_tick_s() > 0


@pytest.mark.parametrize("make", UNAVAILABLE)
def test_s12_meter_unavailable_never_becomes_zero(make, env):
    m = make(env)
    assert isinstance(m.availability(), Unavailable)
    for _ in range(3):
        env.clk.advance(5)
        r = m.tick()
        # sem leitura: nenhuma duração coberta e nenhuma energia (nem zero "medido")
        assert r.duration_s == 0 and r.energy_wh == 0 and r.excluded is None


@pytest.mark.parametrize(("make", "scope", "basis"), AVAILABLE)
def test_s12_meter_tick_never_negative_and_o1_state(make, scope, basis, env):
    m = make(env)
    before = set(vars(m))
    for i in range(300):
        env.clk.advance(1)
        if env.root is not None:
            (env.root / "intel-rapl:0" / "energy_uj").write_text(f"{(i + 1) * 1000}\n")
        r = m.tick()
        assert r.energy_wh >= 0 and r.duration_s >= 0
    assert set(vars(m)) == before  # nenhum atributo novo (p.ex. histórico) surge com os tiques
    for value in vars(m).values():
        assert not isinstance(value, (list, dict, set)) or len(value) == 0
