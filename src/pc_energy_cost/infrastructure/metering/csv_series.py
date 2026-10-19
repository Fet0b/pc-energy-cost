"""Série CSV `timestamp,watts` (escopo `manual`); limites D14 por linha."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ...domain.energy_estimation.schedule import load_zone
from ...domain.metering.model import Available, Sample, SampleUnit, Scope, Unavailable
from ...domain.shared.errors import DomainError, InvalidInput
from ...domain.shared.parsing import parse_watts

HEADER = ("timestamp", "watts")
MAX_ROWS = 1_000_000
MAX_FIELD_LEN = 64


def _parse_timestamp(text: str, zone: ZoneInfo) -> datetime:
    if len(text) > MAX_FIELD_LEN or len(text) <= 10:
        raise ValueError("timestamp deve ter data e hora")
    ts = datetime.fromisoformat(text)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=zone)
    return ts


def parse_series(lines: Iterable[str], zone: ZoneInfo | None = None) -> tuple[Sample, ...]:
    """Lê linhas CSV (com cabeçalho) e devolve `Sample`s de potência, na ordem do arquivo."""
    zone = zone or load_zone()
    reader = csv.reader(lines)
    header = next(reader, None)
    if header is None or tuple(header) != HEADER:
        unknown = [c for c in (header or []) if c not in HEADER]
        if unknown:
            raise DomainError(
                "csv_unknown_columns", f"CSV: colunas desconhecidas {unknown}; esperado timestamp,watts"
            )
        raise DomainError("csv_invalid_header", "CSV: cabeçalho deve ser exatamente timestamp,watts")
    samples: list[Sample] = []
    for row in reader:
        if not row:
            continue
        line = reader.line_num
        if len(samples) >= MAX_ROWS:
            raise DomainError("csv_too_many_rows", f"CSV: mais de {MAX_ROWS} linhas")
        if len(row) != 2:
            raise DomainError("csv_invalid_row", f"CSV linha {line}: esperado 2 campos, achei {len(row)}")
        try:
            ts = _parse_timestamp(row[0].strip(), zone)
        except ValueError as exc:
            raise DomainError("csv_invalid_row", f"CSV linha {line}: timestamp inválido") from exc
        try:
            watts = parse_watts(row[1].strip())
        except DomainError as exc:
            raise InvalidInput(f"CSV linha {line}: {exc.message}", code=exc.code) from exc
        samples.append(Sample(ts, watts.value, SampleUnit.WATTS))
    return tuple(samples)


class CsvPowerSeries:
    def __init__(self, path: Path, zone: ZoneInfo | None = None) -> None:
        self._path = Path(path)
        self._zone = zone

    def availability(self) -> Available | Unavailable:
        return Available(Scope.MANUAL)

    def read(self) -> tuple[Sample, ...]:
        try:
            with open(self._path, encoding="utf-8-sig", newline="") as fh:
                return parse_series(fh, self._zone)
        except UnicodeDecodeError as exc:
            raise DomainError("csv_invalid_row", "CSV: codificação inválida") from exc
