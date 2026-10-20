"""Série CSV `timestamp,watts` (escopo `manual`); limites D14 por linha."""

from __future__ import annotations

import csv
import io
import os
import stat
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
# teto do arquivo lido (64 MiB): 1 M linhas de ~35 B cabem com folga; barra /dev/zero e arquivos gigantes
MAX_BYTES = 64 * 1024 * 1024
# linhas em branco toleradas; acima disso são inundação que contornaria MAX_ROWS (só conta amostras)
MAX_BLANK_ROWS = 1_000


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
    blanks = 0
    for row in reader:
        if not row:
            blanks += 1
            if blanks > MAX_BLANK_ROWS:
                raise DomainError("csv_too_many_rows", f"CSV: mais de {MAX_BLANK_ROWS} linhas em branco")
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
        if "\x00" in str(self._path):  # open() levantaria ValueError, indistinguível de bug do parser
            raise InvalidInput("CSV: caminho inválido")
        try:
            text = _read_regular_file(self._path)
            return parse_series(io.StringIO(text, newline=""), self._zone)
        except UnicodeDecodeError as exc:
            raise DomainError("csv_invalid_row", "CSV: codificação inválida") from exc
        except csv.Error as exc:
            raise DomainError("csv_invalid_row", "CSV: conteúdo malformado") from exc
        except OSError as exc:
            raise InvalidInput(f"CSV ilegível: {exc.strerror or type(exc).__name__}") from exc


def _read_regular_file(path: Path) -> str:
    """Lê só arquivo regular de até MAX_BYTES; checa o fd aberto (sem corrida) e sem bloquear em FIFO."""
    # O_NONBLOCK: open de FIFO não trava (não existe no Windows); O_BINARY: só existe no Windows,
    # onde o fd de os.open é de texto por padrão (traduz CRLF e trata 0x1A como fim de arquivo)
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            raise InvalidInput("CSV: não é um arquivo regular")
        data = fh.read(MAX_BYTES + 1)  # +1 detecta excesso mesmo se o arquivo crescer após o fstat
    if len(data) > MAX_BYTES:
        raise InvalidInput(f"CSV: arquivo maior que {MAX_BYTES} bytes")
    return data.decode("utf-8-sig")
