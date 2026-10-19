"""A52: RAPL real (marcador `live`); sem permissão ou fora do Linux, skip com motivo."""

import sys
from decimal import Decimal

import pytest

from pc_energy_cost.domain.metering.model import SampleUnit, Scope, Unavailable
from pc_energy_cost.infrastructure.metering.linux_rapl import (
    DEFAULT_ROOT,
    LinuxRaplProvider,
    SamplingRaplMeter,
)

pytestmark = pytest.mark.live


def test_a52_live_linux_rapl_delta():
    if not sys.platform.startswith("linux"):
        pytest.skip("RAPL via powercap só existe no Linux")
    provider = LinuxRaplProvider(DEFAULT_ROOT)
    availability = provider.availability()
    if isinstance(availability, Unavailable):
        pytest.skip(f"RAPL indisponível neste host: {availability.reason}")
    assert availability.scope is Scope.CPU_PACKAGE
    meter = SamplingRaplMeter(provider, duration_seconds=Decimal(2))
    samples = meter.read()
    assert samples
    assert all(s.unit is SampleUnit.WATTS and s.quantity >= 0 for s in samples)
