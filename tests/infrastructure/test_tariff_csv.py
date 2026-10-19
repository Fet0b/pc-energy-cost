"""Parser CSV de tarifas ANEEL (etapa 10): schema guard, BOM e decimais pt-BR."""

import codecs
from decimal import Decimal
from pathlib import Path

import pytest

from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.infrastructure.aneel.tariff_csv import (
    EXPECTED_COLUMNS,
    check_header,
    parse_tariff_decimal,
    read_tariffs,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "aneel" / "tarifas_eletropaulo.csv"


def _variant(tmp_path: Path, *, bom: bool = False, header: str | None = None) -> Path:
    raw = FIXTURE.read_bytes()
    head, sep, rest = raw.partition(b"\r\n")
    if header is not None:
        head = header.encode("utf-8")
    out = tmp_path / "t.csv"
    out.write_bytes((codecs.BOM_UTF8 if bom else b"") + head + sep + rest)
    return out


def test_expected_columns_are_the_seventeen_of_the_fixture():
    head = FIXTURE.read_text(encoding="utf-8").splitlines()[0]
    assert tuple(c.strip('"') for c in head.split(";")) == EXPECTED_COLUMNS
    assert len(EXPECTED_COLUMNS) == 17


@pytest.mark.parametrize("bom", [False, True])
def test_reads_with_and_without_bom(tmp_path, bom):
    records = list(read_tariffs(_variant(tmp_path, bom=bom)))
    assert len(records) == 52
    first = records[0]
    assert first.cnpj == "61695227000193"
    assert first.tusd == Decimal("295.15") and first.te == Decimal("292.56")
    assert first.reh.startswith("RESOLUÇÃO HOMOLOGATÓRIA")


@pytest.mark.parametrize("bom", [False, True])
@pytest.mark.parametrize("kind", ["renamed", "missing"])
def test_schema_guard(tmp_path, bom, kind):
    cols = list(EXPECTED_COLUMNS)
    if kind == "renamed":
        cols[3] = "NumCNPJ"
    else:
        cols.pop()
    path = _variant(tmp_path, bom=bom, header=";".join(f'"{c}"' for c in cols))
    with pytest.raises(DomainError) as exc:
        check_header(path)
    assert exc.value.code == "schema_mismatch"
    with pytest.raises(DomainError) as exc:
        list(read_tariffs(path))
    assert exc.value.code == "schema_mismatch"


def test_check_header_accepts_fixture():
    check_header(FIXTURE)


@pytest.mark.parametrize(
    "text,expected",
    [(",00", "0.00"), ("295,15", "295.15"), ("1.234,50", "1234.50"), ("0", "0")],
)
def test_pt_br_decimals(text, expected):
    assert parse_tariff_decimal(text) == Decimal(expected)


def test_fixture_with_comma_zero_is_parsed():
    records = list(read_tariffs(FIXTURE))
    assert any(r.tusd == 0 or r.te == 0 for r in records)


def test_invalid_row_is_schema_mismatch(tmp_path):
    path = tmp_path / "bad.csv"
    lines = FIXTURE.read_bytes().split(b"\r\n")
    lines[1] = lines[1].replace(b'"2025-07-04"', b'"abc"', 1)
    path.write_bytes(b"\r\n".join(lines))
    with pytest.raises(DomainError) as exc:
        list(read_tariffs(path))
    assert exc.value.code == "schema_mismatch"


NEGATIVE_FIXTURE = (
    Path(__file__).resolve().parent.parent / "fixtures" / "aneel" / "tarifas_negativas.csv"
)


@pytest.mark.parametrize(
    "text,expected", [("-,69", "-0.69"), ("-7,53", "-7.53"), ("-43,88", "-43.88"), ("-1.234,50", "-1234.50")]
)
def test_negative_real_credit_values_keep_their_sign(text, expected):
    assert parse_tariff_decimal(text) == Decimal(expected)


@pytest.mark.parametrize("bad", ["", "-", "--1", "1-", "abc", "-,", "- 1"])
def test_malformed_tariff_decimals_still_rejected(bad):
    with pytest.raises(DomainError):
        parse_tariff_decimal(bad)


def test_real_negative_rows_outside_the_profile_parse_and_are_not_zeroed():
    # linhas reais (byte a byte) com TUSD/TE negativos: a primeira "-7,53"/",00", a última ",69" negativo
    records = list(read_tariffs(NEGATIVE_FIXTURE))
    assert [(r.tusd, r.te) for r in records] == [
        (Decimal("-7.53"), Decimal("0.00")),
        (Decimal("-43.88"), Decimal("0.00")),
        (Decimal("245.31"), Decimal("-0.69")),
    ]
