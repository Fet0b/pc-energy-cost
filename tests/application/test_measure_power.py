"""Caso de uso measure_power (etapa 11): indisponível nunca vira zero; cobertura de contador."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from pc_energy_cost.application.measure_power import measure_power
from pc_energy_cost.domain.metering.model import (
    Available,
    Sample,
    SampleUnit,
    Scope,
    Unavailable,
)
from pc_energy_cost.domain.shared.errors import InsufficientCoverage


class Provider:
    def __init__(self, availability, samples=(), error=None) -> None:
        self._availability, self._samples, self._error = availability, samples, error
        self.reads = 0

    def availability(self):
        return self._availability

    def read(self):
        self.reads += 1
        if self._error:
            raise self._error
        return self._samples


def test_available_returns_samples_scope_and_warnings():
    sample = Sample(datetime(2026, 10, 19, tzinfo=timezone.utc), Decimal("50"), SampleUnit.WATTS)
    provider = Provider(Available(Scope.CPU_PACKAGE, ("partial",)), (sample,))
    result = measure_power(provider)
    assert result.scope is Scope.CPU_PACKAGE and result.samples == (sample,)
    assert result.warnings == ("partial",)


def test_unavailable_propagates_without_zero_and_without_reading():
    provider = Provider(Unavailable("permission_denied"))
    with pytest.raises(Exception) as exc:
        measure_power(provider)
    assert exc.value.code == "unavailable" and exc.value.exit_code == 6
    assert "permission_denied" in exc.value.message
    assert provider.reads == 0


def test_counter_insufficient_coverage_is_exit_6():
    error = InsufficientCoverage("tudo excluído", source="counter")
    with pytest.raises(InsufficientCoverage) as exc:
        measure_power(Provider(Available(Scope.CPU_PACKAGE), error=error))
    assert exc.value.exit_code == 6


def test_excluded_intervals_of_optional_provider_are_carried_over():
    from pc_energy_cost.domain.metering.model import ExcludedInterval

    t0 = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)
    ex = ExcludedInterval(t0, t0.replace(minute=1), "indeterminate_wrap")

    class WithExcluded(Provider):
        def excluded_intervals(self):
            return (ex,)

    result = measure_power(WithExcluded(Available(Scope.CPU_PACKAGE)))
    assert result.excluded == (ex,)
    assert result.window is None
    assert measure_power(Provider(Available(Scope.MANUAL))).excluded == ()


def test_window_of_optional_provider_is_carried_over():
    t0 = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)

    class Windowed(Provider):
        def window(self):
            return (t0, t0.replace(minute=1))

    result = measure_power(Windowed(Available(Scope.CPU_PACKAGE)))
    assert result.window == (t0, t0.replace(minute=1))
