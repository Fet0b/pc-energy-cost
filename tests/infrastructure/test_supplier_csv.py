"""Parsers IndQual e DEC/FEC limite (etapa 10)."""

import codecs
from pathlib import Path

import pytest

from pc_energy_cost.domain.location_supplier.model import Ambiguous, Resolved
from pc_energy_cost.domain.location_supplier.resolver import resolve_supplier
from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.infrastructure.aneel.supplier_csv import (
    INDQUAL_COLUMNS,
    LIMITE_COLUMNS,
    build_coverage_index,
    check_indqual_header,
    check_limite_header,
    read_indqual,
    read_limite,
)

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "aneel"
INDQUAL = FIX / "indqual_capital.csv"
LIMITE = FIX / "limite_recorte.csv"

CASES = {
    "indqual": (INDQUAL, INDQUAL_COLUMNS, check_indqual_header, read_indqual),
    "limite": (LIMITE, LIMITE_COLUMNS, check_limite_header, read_limite),
}


def _variant(tmp_path, src: Path, *, bom: bool, cols: list[str] | None) -> Path:
    raw = src.read_bytes()
    head, sep, rest = raw.partition(b"\r\n")
    if cols is not None:
        head = ";".join(f'"{c}"' for c in cols).encode("ascii")
    out = tmp_path / "v.csv"
    out.write_bytes((codecs.BOM_UTF8 if bom else b"") + head + sep + rest)
    return out


def test_column_counts():
    assert len(INDQUAL_COLUMNS) == 5 and len(LIMITE_COLUMNS) == 8
    for src, cols, _, _ in CASES.values():
        head = src.read_bytes().split(b"\r\n")[0].decode("cp1252")
        assert tuple(c.strip('"') for c in head.split(";")) == cols


@pytest.mark.parametrize("bom", [False, True])
@pytest.mark.parametrize("kind", ["renamed", "missing"])
@pytest.mark.parametrize("name", ["indqual", "limite"])
def test_schema_guard(tmp_path, name, kind, bom):
    src, expected, check, read = CASES[name]
    cols = list(expected)
    if kind == "renamed":
        cols[1] = cols[1] + "X"
    else:
        cols.pop()
    path = _variant(tmp_path, src, bom=bom, cols=cols)
    for call in (check, lambda p: list(read(p))):
        with pytest.raises(DomainError) as exc:
            call(path)
        assert exc.value.code == "schema_mismatch"


@pytest.mark.parametrize("bom", [False, True])
def test_valid_headers_with_and_without_bom(tmp_path, bom):
    check_limite_header(_variant(tmp_path, LIMITE, bom=bom, cols=None))
    check_indqual_header(INDQUAL)


def test_limite_strips_siglas():
    agents = read_limite(LIMITE)
    assert agents["2259"][0].sigla == "ELETROPAULO"
    assert all(a.sigla == a.sigla.strip() for rows in agents.values() for a in rows)
    assert {a.cnpj for a in agents["6818"]} == {"08826596000195", "09095183000140"}


def test_indqual_reads_cp1252_names():
    municipalities, conjuntos = read_indqual(INDQUAL)
    assert municipalities["2304277"].name == "Ererê"
    assert municipalities["3550308"].uf == "SP"
    assert len(conjuntos["3550308"]) == 201


def test_built_index_feeds_resolver():
    index = build_coverage_index(INDQUAL, LIMITE)
    assert isinstance(resolve_supplier("3550308", index), Ambiguous)
    assert isinstance(resolve_supplier("2304277", index), Resolved)
