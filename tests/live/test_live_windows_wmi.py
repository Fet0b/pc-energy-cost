"""A53: WMI real (marcador `live_windows`); só vale em Windows com medidor. Mocks NÃO contam."""

import sys

import pytest

from pc_energy_cost.domain.metering.model import Scope, Unavailable
from pc_energy_cost.infrastructure.metering.windows_wmi import WindowsWmiProvider

pytestmark = pytest.mark.live_windows


def test_a53_live_windows_wmi_meter():
    if sys.platform != "win32":
        pytest.skip("exige Windows real; fakes não contam como live")
    provider = WindowsWmiProvider()
    availability = provider.availability()
    if isinstance(availability, Unavailable):
        pytest.skip(f"sem medidor WMI utilizável neste host: {availability.reason}")
    assert availability.scope is Scope.COMPONENT
    samples = provider.read()
    assert samples and all(s.quantity >= 0 for s in samples)
