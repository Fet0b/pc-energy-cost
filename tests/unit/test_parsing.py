"""Parsing decimal pt-BR/JSON e limites D14 (etapa 2)."""

from datetime import timedelta
from decimal import Decimal

import pytest

from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.domain.shared.parsing import (
    parse_decimal,
    parse_hours,
    parse_max_gap,
    parse_rate,
    parse_watts,
)


@pytest.mark.parametrize(
    "func,text",
    [
        (parse_decimal, "-1"),
        (parse_decimal, "nan"),
        (parse_decimal, "inf"),
        (parse_decimal, "1e400"),
        (parse_decimal, "1E5"),
        (parse_watts, "-1"),
        (parse_watts, "nan"),
        (parse_watts, "inf"),
        (parse_watts, "1e400"),
        (parse_watts, "100000,001"),
        (parse_watts, "1,2345"),
        (parse_hours, "87600,0001"),
        (parse_hours, "1,23456"),
        (parse_rate, "100,000001"),
        (parse_rate, "0,1234567"),
    ],
)
def test_a05_invalid_inputs_have_stable_code(func, text):
    with pytest.raises(DomainError) as exc:
        func(text)
    assert exc.value.code == "invalid_input"
    assert exc.value.exit_code == 2


def test_limits_accepted_at_boundaries():
    assert parse_watts("100000").value == Decimal("100000")
    assert parse_hours("87600").hours == Decimal("87600")
    assert parse_rate("100").value == Decimal("100")
    assert parse_rate("0,78938").value == Decimal("0.78938")


def test_a06_decimal_formats():
    assert parse_decimal("0,5") == Decimal("0.5")
    assert parse_decimal("0.5") == Decimal("0.5")
    assert parse_decimal("1.234,5") == Decimal("1234.5")
    assert parse_decimal("0.125") == Decimal("0.125")
    assert parse_decimal("1234") == Decimal("1234")
    for text in ("1,234.5", "1.234", "999.999"):
        with pytest.raises(DomainError) as exc:
            parse_decimal(text)
        assert exc.value.code == "ambiguous_decimal"


@pytest.mark.parametrize("text", ["", " ", "1,2,3", "1.2.3", "5,", ".5", "1 000", "abc", "+1"])
def test_malformed_is_invalid_input(text):
    with pytest.raises(DomainError) as exc:
        parse_decimal(text)
    assert exc.value.code == "invalid_input"


def test_text_length_limit_32():
    assert parse_decimal("1" * 32) == Decimal("1" * 32)
    with pytest.raises(DomainError) as exc:
        parse_decimal("1" * 33)
    assert exc.value.code == "invalid_input"


def test_parse_max_gap_units():
    assert parse_max_gap("5m") == timedelta(minutes=5)
    assert parse_max_gap("1h") == timedelta(hours=1)
    assert parse_max_gap("30s") == timedelta(seconds=30)


def test_parse_max_gap_bounds():
    assert parse_max_gap("1s") == timedelta(seconds=1)
    assert parse_max_gap("24h") == timedelta(hours=24)
    for bad in ("0s", "86401s", "0m", "25h", "", "5", "m", "1d", "-5m", "1,5h", "1.5h"):
        with pytest.raises(DomainError) as exc:
            parse_max_gap(bad)
        assert exc.value.code == "invalid_input"
