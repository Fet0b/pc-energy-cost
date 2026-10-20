"""Provider Linux RAPL (etapa 13). Sysfs injetado a partir de fixture FAKE; nunca le /sys real."""

import shutil
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from pc_energy_cost.domain.energy_estimation.integration import integrate_power
from pc_energy_cost.domain.metering.model import Available, SampleUnit, Scope, Unavailable
from pc_energy_cost.domain.shared.errors import InsufficientCoverage, InvalidInput
from pc_energy_cost.infrastructure.metering.linux_rapl import LinuxRaplProvider

T0 = datetime(2026, 10, 19, 10, 0, tzinfo=timezone(timedelta(hours=-3)))
SEC = 1_000_000_000


@pytest.fixture
def root(tmp_path, copy_powercap_fake):
    return copy_powercap_fake(tmp_path / "powercap")


def write(root, zone, name, value):
    (root / zone / name).write_text(f"{value}\n")


def add_zone(root, zone, name, **files):
    (root / zone).mkdir()
    (root / zone / "name").write_text(f"{name}\n")
    for k, v in files.items():
        (root / zone / k).write_text(f"{v}\n")


class Clocks:
    def __init__(self):
        self.mono = 5 * SEC
        self.wall = T0

    def advance(self, mono_s, wall_s=None):
        self.mono += int(Decimal(str(mono_s)) * SEC)
        self.wall += timedelta(seconds=float(mono_s if wall_s is None else wall_s))


def provider(root, clk, **kw):
    return LinuxRaplProvider(
        root, monotonic_ns=lambda: clk.mono, wall_clock=lambda: clk.wall, **kw
    )


def two_readings(root, first, second, dt, wall_dt=None, zone="intel-rapl:0", **kw):
    clk = Clocks()
    p = provider(root, clk, **kw)
    write(root, zone, "energy_uj", first)
    p.take_reading()
    clk.advance(dt, wall_dt)
    write(root, zone, "energy_uj", second)
    p.take_reading()
    return p


def test_a35_simple_delta(root):
    p = two_readings(root, 1000, 5000, 1)
    avail = p.availability()
    assert avail == Available(Scope.CPU_PACKAGE)
    (s,) = p.read()
    assert s.unit is SampleUnit.WATTS and s.quantity == Decimal("0.004")
    start, end = p.window()
    res = integrate_power(
        p.read(), start, end, pre_excluded=p.excluded_intervals(), source="counter"
    )
    assert res.partial_data is False


def test_a36_single_wrap(root):
    p = two_readings(root, 9_000_000_000, 100, 2)
    (s,) = p.read()
    assert s.quantity == Decimal("500.00005")
    assert p.excluded_intervals() == ()


def test_a37_indeterminate_wrap(root):
    p = two_readings(root, 9_000_000_000, 100, 10)
    assert p.read() == ()
    (ex,) = p.excluded_intervals()
    assert ex.reason == "indeterminate_wrap"
    start, end = p.window()
    with pytest.raises(InsufficientCoverage) as exc:
        integrate_power(
            p.read(), start, end, pre_excluded=p.excluded_intervals(), source="counter"
        )
    assert exc.value.exit_code == 6


def test_a38_implausible_reset(root):
    p = two_readings(root, 5_000_000_000, 1_000_000_000, 1)
    assert p.read() == ()
    (ex,) = p.excluded_intervals()
    assert ex.reason == "counter_reset_or_invalid"


def test_a39_clock_discontinuity(root):
    p = two_readings(root, 1000, 5000, 1, wall_dt=10)
    assert p.read() == ()
    (ex,) = p.excluded_intervals()
    assert ex.reason == "clock_discontinuity"


def test_a40_zones(root):
    add_zone(root, "intel-rapl:1", "psys", energy_uj=7, max_energy_range_uj=10**10, enabled=1)
    p = two_readings(root, 1000, 5000, 1)
    assert p.availability() == Available(Scope.CPU_PACKAGE)
    assert [z.name for z in p.components()] == ["core", "psys"]
    assert all(z.scope is Scope.COMPONENT for z in p.components())
    assert [s.quantity for s in p.read()] == [Decimal("0.004")]  # psys não somado


def test_a41_permission_denied_never_zero(root, monkeypatch):
    path = root / "intel-rapl:0" / "energy_uj"
    real = Path.read_text

    def fake(self, *a, **k):
        if self == path:
            raise PermissionError("negado")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", fake)
    p = provider(root, Clocks())
    assert p.availability() == Unavailable("permission_denied")
    with pytest.raises(Exception) as exc:
        p.read()
    assert exc.value.code == "unavailable"


def test_a42_zone_disabled(root):
    write(root, "intel-rapl:0", "enabled", 0)
    assert provider(root, Clocks()).availability() == Unavailable("zone_disabled")


def test_no_rapl_zone(tmp_path, root):
    assert provider(tmp_path / "missing", Clocks()).availability() == Unavailable("no_rapl_zone")
    shutil.rmtree(root / "intel-rapl:0:0")
    shutil.rmtree(root / "intel-rapl:0")
    assert provider(root, Clocks()).availability() == Unavailable("no_rapl_zone")


def test_only_nested_or_non_package_means_no_zone(root):
    write(root, "intel-rapl:0", "name", "dram")
    assert provider(root, Clocks()).availability() == Unavailable("no_rapl_zone")


@pytest.mark.parametrize("name,value", [
    ("energy_uj", "abc"), ("max_energy_range_uj", "xyz"),
    ("max_energy_range_uj", 0), ("max_energy_range_uj", -5),
])
def test_invalid_counter(root, name, value):
    write(root, "intel-rapl:0", name, value)
    assert provider(root, Clocks()).availability() == Unavailable("invalid_counter")


def test_dt_max_floor_and_ceiling(root):
    clk = Clocks()
    write(root, "intel-rapl:0", "max_energy_range_uj", 10**8)  # 0,05 s ⇒ piso 0,5 s
    assert provider(root, clk).dt_max_seconds == Decimal("0.5")
    write(root, "intel-rapl:0", "max_energy_range_uj", 10**15)  # teto 60 s
    assert provider(root, clk).dt_max_seconds == Decimal(60)
    write(root, "intel-rapl:0", "max_energy_range_uj", 10**10)
    p = provider(root, clk)
    assert p.dt_max_seconds == Decimal(5)
    assert p.sampling_interval_seconds == Decimal(5)


@pytest.mark.parametrize("value", [0, 10_001])
def test_max_watts_out_of_range(root, value):
    with pytest.raises(InvalidInput) as exc:
        provider(root, Clocks(), max_watts=value)
    assert exc.value.code == "invalid_input"


def test_two_packages_summed(root):
    add_zone(root, "intel-rapl:1", "package-1", energy_uj=100, max_energy_range_uj=10**10, enabled=1)
    clk = Clocks()
    p = provider(root, clk)
    p.take_reading()
    clk.advance(1)
    write(root, "intel-rapl:0", "energy_uj", 5000)
    write(root, "intel-rapl:1", "energy_uj", 2100)
    p.take_reading()
    (s,) = p.read()
    assert s.quantity == Decimal("0.006")


def test_top_level_dram_not_summed(root):
    add_zone(root, "intel-rapl:1", "dram", energy_uj=100, max_energy_range_uj=10**10, enabled=1)
    p = provider(root, Clocks())
    assert p.availability() == Available(Scope.CPU_PACKAGE)
    assert "dram" in [z.name for z in p.components()]


def test_boundaries_are_accepted(root):
    p = two_readings(root, 1000, 5000, 5)  # dt == dt_max (5 s)
    assert len(p.read()) == 1 and p.excluded_intervals() == ()
    p = two_readings(root, 1000, 5000, 1, wall_dt=3)  # |1 - 3| == 2 s, tolerado
    assert len(p.read()) == 1 and p.excluded_intervals() == ()
    p = two_readings(root, 0, 1_000_000_000, 1)  # exatamente P_MAX_W
    assert [s.quantity for s in p.read()] == [Decimal(1000)]
    p = two_readings(root, 0, 1_000_001_000, 1)  # logo acima de P_MAX_W
    assert p.read() == () and p.excluded_intervals()[0].reason == "counter_reset_or_invalid"


# -- SamplingRaplMeter (composição: read() já amostra) ---------------------------------
def _sampling(root, clk, duration=10, step_uj=50_000_000):
    from pc_energy_cost.infrastructure.metering.linux_rapl import SamplingRaplMeter

    p = provider(root, clk)
    counter = [1000]  # valor inicial do energy_uj da fixture
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clk.advance(seconds)
        counter[0] += step_uj
        write(root, "intel-rapl:0", "energy_uj", counter[0])

    return SamplingRaplMeter(p, Decimal(duration), sleep=sleep), p, sleeps


def test_sampling_meter_read_samples_at_min_dtmax_5s_and_exposes_excluded(root):
    meter, p, sleeps = _sampling(root, Clocks())
    assert meter.availability() == Available(Scope.CPU_PACKAGE)
    samples = meter.read()
    assert sleeps == [5.0, 5.0]  # min(dt_max = 5 s, 5 s), duração 10 s
    assert [s.quantity for s in samples] == [Decimal(10), Decimal(10)]  # 50 J / 5 s
    assert meter.excluded_intervals() == ()


def test_sampling_meter_all_excluded_is_counter_insufficient_coverage(root):
    meter, p, _ = _sampling(root, Clocks(), step_uj=9_000_000_000)  # > P_MAX_W
    with pytest.raises(InsufficientCoverage) as exc:
        meter.read()
    assert exc.value.exit_code == 6
    assert {e.reason for e in meter.excluded_intervals()} == {"counter_reset_or_invalid"}


def test_sampling_meter_unavailable_does_not_sleep(tmp_path):
    from pc_energy_cost.infrastructure.metering.linux_rapl import SamplingRaplMeter

    meter = SamplingRaplMeter(
        LinuxRaplProvider(tmp_path / "nada"), Decimal(10), sleep=lambda s: pytest.fail("dormiu")
    )
    assert meter.availability() == Unavailable("no_rapl_zone")
