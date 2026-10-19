"""Leitura streaming de CSV ANEEL com schema guard exato (`;`, aspas, BOM opcional)."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from ...domain.shared.errors import DomainError


def mismatch(message: str) -> DomainError:
    return DomainError("schema_mismatch", message)


def _guard(header: list[str] | None, expected: tuple[str, ...], label: str) -> None:
    if header is None:
        raise mismatch(f"{label}: arquivo vazio")
    if len(set(header)) != len(header) or set(header) != set(expected):
        missing = sorted(set(expected) - set(header))
        extra = sorted(set(header) - set(expected))
        raise mismatch(f"{label}: cabeçalho diferente do esperado (faltando {missing}, extras {extra})")


def check_header(path: Path, expected: tuple[str, ...], encoding: str, label: str) -> None:
    try:
        with open(path, encoding=encoding, newline="") as fh:
            _guard(next(csv.reader(fh, delimiter=";"), None), expected, label)
    except UnicodeDecodeError as exc:
        raise mismatch(f"{label}: codificação inválida") from exc


def iter_rows(
    path: Path, expected: tuple[str, ...], encoding: str, label: str
) -> Iterator[dict[str, str]]:
    """Linhas como dict, valores com `strip()`; levanta `schema_mismatch` em qualquer desvio."""
    try:
        with open(path, encoding=encoding, newline="") as fh:
            reader = csv.reader(fh, delimiter=";")
            header = next(reader, None)
            _guard(header, expected, label)
            assert header is not None
            for row in reader:
                if not row:
                    continue
                if len(row) != len(header):
                    raise mismatch(f"{label}: linha com {len(row)} campos (esperado {len(header)})")
                yield {k: v.strip() for k, v in zip(header, row)}
    except UnicodeDecodeError as exc:
        raise mismatch(f"{label}: codificação inválida") from exc
