"""Provider Windows WMI (etapa 14). Somente fakes: nunca roda PowerShell e NUNCA foi testado em Windows."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from pc_energy_cost.domain.metering.model import Available, SampleUnit, Scope, Unavailable
from pc_energy_cost.domain.shared.errors import UnavailableError
from pc_energy_cost.infrastructure.metering import windows_wmi
from pc_energy_cost.infrastructure.metering.windows_wmi import WindowsWmiProvider

T0 = datetime(2026, 10, 19, 10, 0, tzinfo=timezone(timedelta(hours=-3)))

FULL = {
    "MeterType": 0, "BaseUnits": 7, "UnitModifier": -3, "CurrentReading": 150000,
    "Status": "OK", "SupportCapabilities": 0, "SamplingPeriod": 1000,
}


class FakeRunner:
    def __init__(self, stdout="", rc=0, exc=None):
        self.stdout, self.rc, self.exc, self.calls = stdout, rc, exc, []

    def __call__(self, argv, timeout):
        self.calls.append((tuple(argv), timeout))
        if self.exc:
            raise self.exc
        return self.rc, self.stdout


def inst(**over):
    d = dict(FULL)
    for k, v in over.items():
        if v is ...:
            d.pop(k, None)
        else:
            d[k] = v
    return d


def prov(*instances, clock=None, **kw):
    out = json.dumps(instances[0] if len(instances) == 1 else list(instances)) if instances else ""
    runner = FakeRunner(out)
    return WindowsWmiProvider(runner=runner, wall_clock=clock or (lambda: T0), **kw), runner


def test_a43_no_instances_or_missing_class():
    for runner in (
        FakeRunner(""), FakeRunner("[]"), FakeRunner("", rc=1),
        FakeRunner(exc=subprocess.TimeoutExpired("powershell.exe", 10)), FakeRunner(exc=FileNotFoundError()),
        FakeRunner("not json"),
    ):
        p = WindowsWmiProvider(runner=runner, wall_clock=lambda: T0)
        assert p.availability() == Unavailable("no_power_meter_provider")
        with pytest.raises(UnavailableError):
            p.read()


def test_a44_never_whole_system_always_component():
    for meter_type in (0, 1, ...):
        p, _ = prov(inst(MeterType=meter_type))
        av = p.availability()
        assert isinstance(av, Available)
        assert av.scope is Scope.COMPONENT
        assert av.scope not in (Scope.WHOLE_SYSTEM_AC, Scope.WHOLE_SYSTEM_UNVERIFIED)
    p0, _ = prov(inst(MeterType=0))
    p1, _ = prov(inst(MeterType=1))
    assert "output_or_unknown_power" not in p0.availability().warnings
    assert "output_or_unknown_power" in p1.availability().warnings
    assert p0.meter_label == "potência de entrada (domínio não comprovado)"
    assert p1.meter_label == "potência de saída/desconhecida"


@pytest.mark.parametrize(
    "over, reason",
    [
        ({"CurrentReading": None}, "reading_property_unverified"),
        ({"CurrentReading": ...}, "reading_property_unverified"),
        ({"CurrentReading": "abc"}, "reading_property_unverified"),
        ({"UnitModifier": ...}, "unit_unknown"),
        ({"BaseUnits": ...}, "unit_unknown"),
        ({"SupportCapabilities": 8}, "only_when_discharging"),
        ({"SupportCapabilities": 256}, "only_when_discharging"),
        ({"CurrentReading": -1}, "invalid_reading"),
        ({"Status": "Degraded"}, "invalid_reading"),
    ],
)
def test_a45_doubtful_reading(over, reason):
    p, _ = prov(inst(**over))
    assert p.availability() == Unavailable(reason)
    with pytest.raises(UnavailableError):
        p.read()


def test_a46_scaled_reading():
    p, _ = prov(inst())
    av = p.availability()
    assert isinstance(av, Available) and av.scope is Scope.COMPONENT
    assert "base_units_not_decoded" in av.warnings
    assert "status_not_exposed" not in av.warnings
    assert p.base_units_code == 7
    assert p.reading_provenance == "herdada, não validada em hardware"
    (s,) = p.read()
    assert s.quantity == Decimal(150) and s.unit is SampleUnit.WATTS and s.timestamp == T0


def test_status_absent_is_accepted_with_warning():
    p, _ = prov(inst(Status=...))
    av = p.availability()
    assert isinstance(av, Available) and "status_not_exposed" in av.warnings


def test_reading_above_100000_w_is_invalid():
    p, _ = prov(inst(CurrentReading=100_001_000))
    assert p.availability() == Unavailable("invalid_reading")
    p, _ = prov(inst(CurrentReading=100_000_000))
    assert isinstance(p.availability(), Available)


def test_zero_watts_is_a_real_reading_not_fabricated():
    p, _ = prov(inst(CurrentReading=0))
    assert [s.quantity for s in p.read()] == [Decimal(0)]


def test_fixed_command_without_interpolation_and_10s_timeout():
    p, runner = prov(inst())
    p.availability()
    argv, timeout = runner.calls[0]
    assert timeout == 10
    assert argv[:4] == ("powershell.exe", "-NoProfile", "-NonInteractive", "-Command")
    assert len(argv) == 5
    assert "Get-CimInstance -Namespace root/CIMV2/power -ClassName Win32_PowerMeter" in argv[4]
    assert list(argv) == windows_wmi.COMMAND
    # nenhum parâmetro do construtor altera o comando
    p2 = WindowsWmiProvider(runner=runner, wall_clock=lambda: T0)
    p2.availability()
    assert runner.calls[-1][0] == argv


def test_default_runner_uses_no_shell_and_timeout(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        return subprocess.CompletedProcess(argv, 0, stdout="x", stderr="")

    monkeypatch.setattr(windows_wmi.subprocess, "run", fake_run)
    assert windows_wmi.run_powershell(windows_wmi.COMMAND, 10) == (0, "x")
    assert seen["kw"].get("shell", False) is False and seen["kw"]["timeout"] == 10
    assert isinstance(seen["argv"], list)


def test_no_writes_to_writable_properties():
    cmd = " ".join(windows_wmi.COMMAND)
    for forbidden in ("ConfiguredBudget", "BudgetEnabled", "AveragingInterval", "Set-", "Invoke-", "Remove-", "New-"):
        assert forbidden not in cmd
    assert "Get-CimInstance" in cmd


def test_repeated_read_within_sampling_period_is_not_new_sample():
    now = [T0]
    p, runner = prov(inst(SamplingPeriod=1000), clock=lambda: now[0])
    assert len(p.read()) == 1
    calls = len(runner.calls)
    now[0] = T0 + timedelta(milliseconds=500)
    assert len(p.read()) == 1
    assert len(runner.calls) == calls
    now[0] = T0 + timedelta(milliseconds=1000)
    assert len(p.read()) == 2
