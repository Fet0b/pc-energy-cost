"""Contrato do Metering: a mesma suíte para manual, csv, rapl-fake e wmi-fake (nada é hardware real)."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pc_energy_cost.domain.metering.model import Available, Sample, Scope, Unavailable
from pc_energy_cost.domain.shared.errors import UnavailableError
from pc_energy_cost.infrastructure.metering.csv_series import CsvPowerSeries
from pc_energy_cost.infrastructure.metering.linux_rapl import LinuxRaplProvider
from pc_energy_cost.infrastructure.metering.manual import ManualAverageWatts
from pc_energy_cost.infrastructure.metering.windows_wmi import WindowsWmiProvider

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "metering"
T0 = datetime(2026, 10, 19, 10, 0, tzinfo=timezone(timedelta(hours=-3)))
WMI_OK = {
    "MeterType": 0, "BaseUnits": 7, "UnitModifier": -3, "CurrentReading": 150000,
    "Status": "OK", "SupportCapabilities": 0, "SamplingPeriod": 1000,
}


_COPY_POWERCAP = None


@pytest.fixture(autouse=True)
def _powercap_copier(copy_powercap_fake):
    global _COPY_POWERCAP
    _COPY_POWERCAP = copy_powercap_fake


def _manual(tmp_path):
    return ManualAverageWatts("120")


def _csv(tmp_path):
    return CsvPowerSeries(FIX / "serie_valida.csv")


def _rapl(tmp_path):
    root = _COPY_POWERCAP(tmp_path / "powercap")
    p = LinuxRaplProvider(root)
    p.take_reading()
    return p


def _wmi(tmp_path):
    return WindowsWmiProvider(runner=lambda argv, timeout: (0, json.dumps(WMI_OK)), wall_clock=lambda: T0)


def _rapl_missing(tmp_path):
    return LinuxRaplProvider(tmp_path / "nao_existe")


def _wmi_missing(tmp_path):
    return WindowsWmiProvider(runner=lambda argv, timeout: (0, ""), wall_clock=lambda: T0)


AVAILABLE = [
    pytest.param(_manual, Scope.MANUAL, id="manual"),
    pytest.param(_csv, Scope.MANUAL, id="csv"),
    pytest.param(_rapl, Scope.CPU_PACKAGE, id="rapl-fake"),
    pytest.param(_wmi, Scope.COMPONENT, id="wmi-fake"),
]
UNAVAILABLE = [
    pytest.param(_rapl_missing, id="rapl-fake"),
    pytest.param(_wmi_missing, id="wmi-fake"),
]


@pytest.mark.parametrize("factory, scope", AVAILABLE)
def test_a34_available_providers_share_contract(factory, scope, tmp_path):
    p = factory(tmp_path)
    av = p.availability()
    assert isinstance(av, Available)
    assert isinstance(av.scope, Scope) and av.scope is scope
    assert av.scope is not Scope.WHOLE_SYSTEM_AC
    assert isinstance(av.warnings, tuple)
    samples = p.read()
    assert isinstance(samples, tuple) and all(isinstance(s, Sample) for s in samples)
    # nada de zero fabricado: uma fonte sem leitura real devolve vazio, não amostras nulas
    if factory in (_manual, _rapl):
        assert samples == ()
    else:
        assert samples and any(s.quantity > 0 for s in samples)


@pytest.mark.parametrize("factory", UNAVAILABLE)
def test_metering_unavailable_providers_never_fabricate_zero(factory, tmp_path):
    p = factory(tmp_path)
    av = p.availability()
    assert isinstance(av, Unavailable) and av.reason
    with pytest.raises(UnavailableError):
        p.read()
