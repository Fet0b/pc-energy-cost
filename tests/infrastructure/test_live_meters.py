"""Medidores ao vivo (S12): RAPL sobre fixture FAKE, WMI com runner fake, potência informada."""

import gc
import json
import tracemalloc
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from pc_energy_cost.domain.metering.model import Available, Scope, Unavailable
from pc_energy_cost.domain.usage_session.model import EnergyBasis
from pc_energy_cost.infrastructure.metering.live_manual import LiveManualPower
from pc_energy_cost.infrastructure.metering.live_rapl import LiveRaplMeter
from pc_energy_cost.infrastructure.metering.live_wmi import LiveWmiMeter

SEC = 1_000_000_000
T0 = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
WMI_OK = {
    "MeterType": 0, "BaseUnits": 7, "UnitModifier": -3, "CurrentReading": 120000,
    "Status": "OK", "SupportCapabilities": 0, "SamplingPeriod": 1000,
}


class Clk:
    def __init__(self):
        self.mono, self.wall = 5 * SEC, T0

    def advance(self, s, wall_s=None):
        self.mono += int(Decimal(str(s)) * SEC)
        self.wall += timedelta(seconds=float(s if wall_s is None else wall_s))


def _set(root, uj):
    (root / "intel-rapl:0" / "energy_uj").write_text(f"{uj}\n")


@pytest.fixture
def rapl(tmp_path, copy_powercap_fake):
    root = copy_powercap_fake(tmp_path / "powercap")
    clk = Clk()
    meter = LiveRaplMeter(root, monotonic_ns=lambda: clk.mono, wall_clock=lambda: clk.wall)
    return meter, root, clk


# ------------------------------------------------------------------ RAPL
def test_s12_rapl_basis_scope_and_max_tick(rapl):
    meter, _, _ = rapl
    assert meter.energy_basis() is EnergyBasis.MEASURED_COUNTER
    assert meter.availability() == Available(Scope.CPU_PACKAGE)
    assert 0 < meter.max_tick_s() <= 5


def test_s12_rapl_first_tick_has_no_reading_then_energy(rapl):
    meter, root, clk = rapl
    _set(root, 0)
    first = meter.tick()
    assert first.duration_s == 0 and first.energy_wh == 0 and first.excluded is None
    clk.advance(5)
    _set(root, 500_000_000)  # 100 W durante 5 s
    r = meter.tick()
    assert r.duration_s == Decimal(5) and not r.assumed and r.excluded is None
    assert r.energy_wh == Decimal(500) / Decimal(3600)


def test_s12_rapl_wrap_inside_range_is_counted(rapl):
    meter, root, clk = rapl
    _set(root, 9_900_000_000)
    meter.tick()
    clk.advance(4)
    _set(root, 100_000_000)  # deu a volta: 200 MJ... = 200_000_000 uJ em 4 s = 50 W
    r = meter.tick()
    assert r.excluded is None and r.duration_s == 4
    assert r.energy_wh == Decimal(200) / Decimal(3600)


def test_s12_rapl_reports_indeterminate_wrap_itself(rapl):
    meter, root, clk = rapl
    _set(root, 0)
    meter.tick()
    clk.advance(30)  # > dt_max
    _set(root, 1000)
    r = meter.tick()
    assert r.excluded is not None and r.excluded.reason == "indeterminate_wrap"
    assert r.energy_wh == 0 and r.duration_s == 0


def test_s12_rapl_reports_clock_discontinuity(rapl):
    meter, root, clk = rapl
    _set(root, 0)
    meter.tick()
    clk.advance(3, wall_s=3600)
    _set(root, 1000)
    r = meter.tick()
    assert r.excluded is not None and r.excluded.reason == "clock_discontinuity"


def test_s12_rapl_implausible_counter_is_excluded(rapl):
    meter, root, clk = rapl
    _set(root, 0)
    meter.tick()
    clk.advance(1)
    _set(root, 5_000_000_000)  # 5000 W > p_max
    r = meter.tick()
    assert r.excluded is not None and r.excluded.reason == "counter_reset_or_invalid"


def test_s12_rapl_unavailable_never_becomes_zero_reading(tmp_path):
    clk = Clk()
    meter = LiveRaplMeter(tmp_path / "nao_existe", monotonic_ns=lambda: clk.mono,
                          wall_clock=lambda: clk.wall)
    assert isinstance(meter.availability(), Unavailable)
    r = meter.tick()
    assert r.duration_s == 0 and r.energy_wh == 0 and r.excluded is None


def test_s12_rapl_read_failure_after_start_keeps_no_fake_energy(rapl):
    meter, root, clk = rapl
    _set(root, 0)
    meter.tick()
    (root / "intel-rapl:0" / "energy_uj").write_text("lixo\n")
    clk.advance(5)
    assert meter.tick().duration_s == 0
    clk.advance(5)
    _set(root, 10)
    r = meter.tick()  # a lacuna não vira energia nem tempo coberto
    assert r.duration_s == 0 or r.excluded is not None


def test_s12_rapl_short_read_failure_does_not_span_the_failure(rapl):
    meter, root, clk = rapl
    _set(root, 0)
    meter.tick()
    (root / "intel-rapl:0" / "energy_uj").write_text("lixo\n")
    clk.advance(2)
    assert meter.tick().duration_s == 0
    clk.advance(2)  # bem abaixo de dt_max: sem o reset, o par cobriria a falha
    _set(root, 400_000_000)
    r = meter.tick()
    assert r.duration_s == 0 and r.energy_wh == 0 and r.excluded is None


def _retained_growth(run, n):
    """Bytes retidos após `n` tiques (com coleta de ciclos): lixo ainda não coletado não conta."""
    gc.collect()
    tracemalloc.start()
    base = tracemalloc.take_snapshot()
    run(n)
    gc.collect()
    grown = sum(s.size_diff for s in tracemalloc.take_snapshot().compare_to(base, "filename"))
    tracemalloc.stop()
    return grown


def test_s12_rapl_memory_does_not_grow_with_ticks(rapl):
    meter, root, clk = rapl
    _set(root, 0)
    meter.tick()
    counter = [0]

    def run(n):
        for _ in range(n):
            clk.advance(1)
            counter[0] = (counter[0] + 1000) % 1_000_000_000
            _set(root, counter[0])
            meter.tick()

    run(200)
    # estrutural: nenhuma coleção cresce, nenhum histórico no medidor nem no provider interno
    assert not hasattr(meter, "_history") and not meter._provider._history
    state = set(vars(meter))
    # empírico: um histórico custaria ~centenas de bytes por tique (MB em 3000 tiques);
    # após gc o resíduo medido é de poucos KB e não escala com n
    assert _retained_growth(run, 3000) < 40_000
    assert not meter._provider._history and set(vars(meter)) == state


# ------------------------------------------------------------------ WMI
def _wmi(clk, payload=WMI_OK, rc=0, calls=None):
    state = {"payload": payload, "rc": rc}

    def runner(argv, timeout):
        if calls is not None:
            calls.append((tuple(argv), timeout))
        p = state["payload"]
        return state["rc"], (json.dumps(p) if p is not None else "")

    meter = LiveWmiMeter(runner=runner, monotonic_ns=lambda: clk.mono, wall_clock=lambda: clk.wall)
    return meter, state


def test_s12_wmi_basis_scope_and_runner_injected():
    clk, calls = Clk(), []
    meter, _ = _wmi(clk, calls=calls)
    assert meter.energy_basis() is EnergyBasis.MEASURED_POWER
    assert meter.availability().scope is Scope.COMPONENT
    assert meter.max_tick_s() > 0
    assert calls and all(t > 0 for _, t in calls)


def test_s12_wmi_integrates_by_steps_between_ticks():
    clk = Clk()
    meter, state = _wmi(clk)
    assert meter.tick().duration_s == 0  # primeira leitura
    clk.advance(5)
    r = meter.tick()
    assert r.duration_s == 5 and not r.assumed
    assert r.energy_wh == Decimal(120) * 5 / 3600
    state["payload"] = {**WMI_OK, "CurrentReading": 60000}
    clk.advance(5)
    r = meter.tick()  # degrau: usa a potência da leitura anterior (120 W)
    assert r.energy_wh == Decimal(120) * 5 / 3600
    clk.advance(5)
    assert meter.tick().energy_wh == Decimal(60) * 5 / 3600


def test_s12_wmi_unavailable_never_becomes_zero():
    clk = Clk()
    meter, state = _wmi(clk, payload=None)
    assert isinstance(meter.availability(), Unavailable)
    r = meter.tick()
    assert r.duration_s == 0 and r.energy_wh == 0
    state["payload"] = WMI_OK
    meter.tick()
    clk.advance(5)
    state["payload"] = None
    r = meter.tick()
    assert r.duration_s == 0 and r.energy_wh == 0
    state["payload"] = WMI_OK
    clk.advance(5)
    assert meter.tick().duration_s == 0  # sem leitura anterior: recomeça


def test_s12_wmi_long_gap_is_excluded_not_integrated():
    clk = Clk()
    meter, _ = _wmi(clk)
    meter.tick()
    clk.advance(600)
    r = meter.tick()
    assert r.excluded is not None and r.excluded.reason == "gap" and r.energy_wh == 0


def test_s12_wmi_memory_does_not_grow_with_ticks():
    clk = Clk()
    meter, _ = _wmi(clk)
    meter.tick()

    def run(n):
        for _ in range(n):
            clk.advance(1)
            meter.tick()

    run(200)
    assert _retained_growth(run, 2000) < 40_000


# ------------------------------------------------------------------ manual
class Mono:
    def __init__(self):
        self.ns = 0

    def monotonic_ns(self):
        return self.ns


def test_s12_manual_matches_assumed_semantics():
    mono = Mono()
    m = LiveManualPower(Decimal(100), mono)
    assert m.energy_basis() is EnergyBasis.USER_POWER
    assert m.availability() == Available(Scope.MANUAL)
    assert m.max_tick_s() > 0
    mono.ns = 36 * SEC
    r = m.tick()
    assert r.assumed and r.duration_s == 36 and r.energy_wh == Decimal(1)


def test_s12_manual_scenario_basis():
    m = LiveManualPower(Decimal(50), Mono(), basis=EnergyBasis.SCENARIO)
    assert m.energy_basis() is EnergyBasis.SCENARIO
    assert m.availability().scope is Scope.SCENARIO


def test_s12_manual_rejects_measured_basis():
    from pc_energy_cost.domain.shared.errors import InvalidInput
    with pytest.raises(InvalidInput):
        LiveManualPower(Decimal(50), Mono(), basis=EnergyBasis.MEASURED_POWER)
