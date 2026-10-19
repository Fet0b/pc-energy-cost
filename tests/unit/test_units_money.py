"""Unidades (etapa 1) e dinheiro (etapa 2)."""

import tomllib
from decimal import Decimal
from pathlib import Path

import pytest

from pc_energy_cost.domain.shared.errors import (
    DomainError,
    InsufficientCoverage,
    InvalidInput,
    exit_code_for,
)
from pc_energy_cost.domain.shared.money import MoneyBRL
from pc_energy_cost.domain.shared.units import (
    Duration,
    KWh,
    UnitRateBRLPerKWh,
    Watts,
    Wh,
)

ROOT = Path(__file__).resolve().parents[2]


def test_a01_100w_10h_is_1_kwh():
    energy = Watts(Decimal("100")).energy_over(Duration(Decimal("10")))
    assert isinstance(energy, KWh)
    assert energy.value == Decimal("1")
    assert energy.display() == "1,000"


def test_kwh_display_round_half_up_keeps_internal_value():
    energy = Watts(Decimal("1.5")).energy_over(Duration(Decimal("1")))
    assert energy.value == Decimal("0.0015")
    assert energy.display() == "0,002"
    assert Wh(Decimal("1.5")).to_kwh().value == Decimal("0.0015")


@pytest.mark.parametrize("bad", [-1, Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_watts_rejects_negative_nan_inf(bad):
    with pytest.raises(InvalidInput) as exc:
        Watts(Decimal(bad))
    assert exc.value.code == "invalid_input"


def test_zero_is_valid():
    assert Watts(Decimal("0")).value == 0
    assert Duration(Decimal("0")).hours == 0
    assert Watts(Decimal("0")).energy_over(Duration(Decimal("5"))).value == 0


def test_exact_limits_accepted_and_beyond_rejected():
    assert Watts(Decimal("100000")).value == Decimal("100000")
    assert Duration(Decimal("87600")).hours == Decimal("87600")
    with pytest.raises(InvalidInput):
        Watts(Decimal("100000.001"))
    with pytest.raises(InvalidInput):
        Duration(Decimal("87600.0001"))


def test_decimal_places_limits():
    with pytest.raises(InvalidInput):
        Watts(Decimal("1.2345"))
    with pytest.raises(InvalidInput):
        Duration(Decimal("1.23456"))
    with pytest.raises(InvalidInput):
        UnitRateBRLPerKWh(Decimal("0.1234567"))
    assert UnitRateBRLPerKWh(Decimal("100")).value == Decimal("100")
    with pytest.raises(InvalidInput):
        UnitRateBRLPerKWh(Decimal("100.000001"))


def test_float_is_rejected():
    with pytest.raises(InvalidInput):
        Watts(1.5)  # type: ignore[arg-type]


D13 = {
    2: [
        "invalid_input", "ambiguous_decimal", "invalid_interval",
        "overlapping_intervals", "timezone_data_missing", "double_inclusion",
        "inclusion_undeclared", "csv_conflicting_duplicate", "csv_unknown_columns",
        "csv_invalid_header",
        "csv_invalid_row", "csv_too_many_rows",
    ],
    3: ["supplier_ambiguous", "unsupported", "tariff_ambiguous"],
    4: [
        "tariff_not_found", "tariff_not_in_effect", "schema_mismatch",
        "unexpected_html", "download_incomplete", "cache_corrupted",
    ],
    5: ["network_unavailable"],
    6: ["unavailable"],
}


@pytest.mark.parametrize(
    "code,expected", [(c, e) for e, codes in D13.items() for c in codes]
)
def test_d13_code_to_exit_code_table(code, expected):
    assert exit_code_for(code) == expected
    assert DomainError(code, "msg").exit_code == expected


def test_unknown_code_is_rejected():
    with pytest.raises(ValueError):
        DomainError("not_a_code", "x")


def test_insufficient_coverage_source_decides_exit():
    assert InsufficientCoverage("m", source="csv").exit_code == 2
    assert InsufficientCoverage("m", source="counter").exit_code == 6
    assert InsufficientCoverage("m", source="csv").code == "insufficient_coverage"
    with pytest.raises(ValueError):
        InsufficientCoverage("m", source="other")


def test_pyproject_tzdata_marker_and_addopts():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert 'tzdata; sys_platform == "win32"' in data["project"]["dependencies"]
    assert "not install" in data["tool"]["pytest"]["ini_options"]["addopts"]


def test_a02_one_kwh_times_rate_displays_rounded_keeps_internal():
    money = MoneyBRL.of(KWh(Decimal("1")), UnitRateBRLPerKWh(Decimal("0.78938")))
    assert money.display() == "R$ 0,79"
    assert money.value == Decimal("0.78938")


def test_a03_round_half_up_not_bankers():
    rate = UnitRateBRLPerKWh(Decimal("1.00"))
    assert MoneyBRL.of(KWh(Decimal("0.125")), rate).display() == "R$ 0,13"
    assert MoneyBRL.of(KWh(Decimal("0.135")), rate).display() == "R$ 0,14"


def test_a07_brl_format_and_json_string():
    money = MoneyBRL(Decimal("1234.5"))
    assert money.display() == "R$ 1.234,50"
    assert money.to_json() == "1234.50"
    assert isinstance(money.to_json(), str)


def test_money_total_rounds_only_once():
    parts = [MoneyBRL(Decimal("0.004")), MoneyBRL(Decimal("0.004")), MoneyBRL(Decimal("0.002"))]
    total = MoneyBRL.total(parts)
    assert total.value == Decimal("0.01")
    assert total.display() == "R$ 0,01"


def test_money_rejects_float_and_non_finite():
    with pytest.raises(InvalidInput):
        MoneyBRL(1.5)  # type: ignore[arg-type]
    with pytest.raises(InvalidInput):
        MoneyBRL(Decimal("NaN"))
