"""Providers manual e série CSV (etapa 12). Fixtures de medição são sintéticas."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from pc_energy_cost.domain.energy_estimation.integration import integrate_power
from pc_energy_cost.domain.metering.model import Available, SampleUnit, Scope
from pc_energy_cost.domain.shared.errors import DomainError, InsufficientCoverage, InvalidInput
from pc_energy_cost.infrastructure.metering.csv_series import (
    MAX_ROWS,
    CsvPowerSeries,
    parse_series,
)
from pc_energy_cost.infrastructure.metering.manual import ManualAverageWatts

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "metering"
BRT = timezone(timedelta(hours=-3))


def test_a15_energy_series_rejected_by_header():
    with pytest.raises(DomainError) as exc:
        parse_series(["timestamp,energy_wh", "2026-10-19T10:00:00-03:00,5"])
    assert exc.value.code == "csv_unknown_columns"
    assert exc.value.exit_code == 2


def test_header_wrong_order_or_missing_is_invalid_header():
    for header in ("watts,timestamp", "timestamp", ""):
        with pytest.raises(DomainError) as exc:
            parse_series([header])
        assert exc.value.code == "csv_invalid_header"


def test_valid_series_offset_and_naive():
    samples = CsvPowerSeries(FIX / "serie_valida.csv").read()
    assert [s.quantity for s in samples] == [
        Decimal("100"), Decimal("150.5"), Decimal("200"), Decimal("0"), Decimal("120"),
    ]
    assert all(s.unit is SampleUnit.WATTS for s in samples)
    assert samples[0].timestamp == datetime(2026, 10, 19, 10, 0, tzinfo=BRT)
    # naive interpretado em America/Sao_Paulo (-03:00)
    assert samples[2].timestamp.utcoffset() == timedelta(hours=-3)
    assert samples[2].timestamp == datetime(2026, 10, 19, 10, 2, tzinfo=BRT)
    assert samples[3].timestamp == datetime(2026, 10, 19, 10, 3, tzinfo=BRT)
    assert samples[4].timestamp == datetime(2026, 10, 19, 10, 4, tzinfo=BRT)


def test_valid_series_integrates():
    samples = CsvPowerSeries(FIX / "serie_valida.csv").read()
    res = integrate_power(
        samples, samples[0].timestamp, samples[-1].timestamp, max_gap=timedelta(minutes=5)
    )
    assert not res.partial_data
    assert res.coverage_duration == timedelta(minutes=4)


def test_invalid_row_reports_line_number():
    with pytest.raises(DomainError) as exc:
        CsvPowerSeries(FIX / "serie_invalida.csv").read()
    assert exc.value.code == "csv_invalid_row"
    assert "linha 3" in exc.value.message


def test_wrong_field_count_reports_line_number():
    with pytest.raises(DomainError) as exc:
        parse_series(["timestamp,watts", "2026-10-19T10:00:00,1", "2026-10-19T10:01:00"])
    assert exc.value.code == "csv_invalid_row"
    assert "linha 3" in exc.value.message


@pytest.mark.parametrize(
    "watts", ["-1", "NaN", "inf", "100000.001", "1.2345", "1e3", "abc", ""]
)
def test_invalid_watts_per_row(watts):
    with pytest.raises(InvalidInput) as exc:
        parse_series(["timestamp,watts", "2026-10-19T10:00:00,5", f"2026-10-19T10:01:00,{watts}"])
    assert exc.value.code == "invalid_input"
    assert "linha 3" in exc.value.message


def test_watts_limits_accepted():
    s = parse_series(["timestamp,watts", "2026-10-19T10:00:00,100000", "2026-10-19T10:01:00,0.125"])
    assert [x.quantity for x in s] == [Decimal("100000"), Decimal("0.125")]


def test_row_limit_in_memory():
    def lines(n):
        yield "timestamp,watts"
        for _ in range(n):
            yield "2026-10-19T10:00:00,1"

    assert MAX_ROWS == 1_000_000
    with pytest.raises(DomainError) as exc:
        parse_series(lines(MAX_ROWS + 1))
    assert exc.value.code == "csv_too_many_rows"


def test_gap_fixture_default_max_gap_is_partial():
    samples = CsvPowerSeries(FIX / "serie_gap.csv").read()
    res = integrate_power(samples, samples[0].timestamp, samples[-1].timestamp)
    assert res.partial_data
    assert res.excluded_duration == timedelta(minutes=55)
    assert res.coverage_duration == timedelta(minutes=10)


def test_gap_series_without_coverage_is_insufficient():
    samples = parse_series(
        ["timestamp,watts", "2026-10-19T10:00:00,100", "2026-10-19T11:00:00,100"]
    )
    with pytest.raises(InsufficientCoverage) as exc:
        integrate_power(samples, samples[0].timestamp, samples[-1].timestamp)
    assert exc.value.exit_code == 2


def test_conflicting_duplicate_surfaces_in_integration():
    samples = parse_series(
        ["timestamp,watts", "2026-10-19T10:00:00,1", "2026-10-19T10:00:00,2"]
    )
    with pytest.raises(DomainError) as exc:
        integrate_power(samples, samples[0].timestamp, samples[0].timestamp + timedelta(minutes=1))
    assert exc.value.code == "csv_conflicting_duplicate"


def test_csv_scope_is_manual():
    avail = CsvPowerSeries(FIX / "serie_valida.csv").availability()
    assert isinstance(avail, Available) and avail.scope is Scope.MANUAL


def test_manual_zero_is_valid():
    p = ManualAverageWatts("0")
    assert p.watts.value == Decimal("0")
    avail = p.availability()
    assert isinstance(avail, Available) and avail.scope is Scope.MANUAL
    assert p.read() == ()  # sem série temporal; nunca fabrica amostra


def test_manual_accepts_pt_br_decimal():
    assert ManualAverageWatts("0,5").watts.value == Decimal("0.5")


@pytest.mark.parametrize("bad", ["-1", "NaN", "100000,001"])
def test_manual_invalid(bad):
    with pytest.raises(InvalidInput) as exc:
        ManualAverageWatts(bad)
    assert exc.value.code == "invalid_input"
