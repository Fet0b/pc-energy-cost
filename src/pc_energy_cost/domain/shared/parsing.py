"""Parsing de decimais pt-BR/JSON e de entradas com limites D14 (sem arredondar a entrada)."""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

from .errors import InvalidInput
from .units import Duration, UnitRateBRLPerKWh, Watts

MAX_TEXT_LEN = 32

_PLAIN = re.compile(r"\d+", re.ASCII)
_COMMA = re.compile(r"\d+,\d+", re.ASCII)
_DOT = re.compile(r"(\d+)\.(\d+)", re.ASCII)
_BR_BOTH = re.compile(r"\d{1,3}(?:\.\d{3})+,\d+", re.ASCII)
_US_BOTH = re.compile(r"\d{1,3}(?:,\d{3})+\.\d+", re.ASCII)
_GAP = re.compile(r"(\d+)([smh])", re.ASCII)
_GAP_SECONDS = {"s": 1, "m": 60, "h": 3600}


def parse_decimal(text: str) -> Decimal:
    """Decimal pt-BR (`1.234,5`) ou JSON (`0.5`); formas ambíguas são rejeitadas."""
    if not isinstance(text, str):
        raise InvalidInput("número: esperado texto")
    if len(text) > MAX_TEXT_LEN:
        raise InvalidInput(f"número: texto acima de {MAX_TEXT_LEN} caracteres")
    text = text.strip()
    if _PLAIN.fullmatch(text):
        return Decimal(text)
    if _COMMA.fullmatch(text):
        return Decimal(text.replace(",", "."))
    if _BR_BOTH.fullmatch(text):
        return Decimal(text.replace(".", "").replace(",", "."))
    if _US_BOTH.fullmatch(text):
        raise InvalidInput(
            "número ambíguo: use vírgula decimal (ex.: 1.234,5)", code="ambiguous_decimal"
        )
    m = _DOT.fullmatch(text)
    if m:
        integer, frac = m.groups()
        if len(frac) == 3 and len(integer) <= 3 and integer != "0":
            raise InvalidInput(
                "número ambíguo: ponto pode ser milhar ou decimal", code="ambiguous_decimal"
            )
        return Decimal(text)
    raise InvalidInput("número inválido")


def parse_watts(text: str) -> Watts:
    return Watts(parse_decimal(text))


def parse_hours(text: str) -> Duration:
    return Duration(parse_decimal(text))


def parse_rate(text: str) -> UnitRateBRLPerKWh:
    return UnitRateBRLPerKWh(parse_decimal(text))


def parse_max_gap(text: str) -> timedelta:
    """`30s`, `5m` ou `1h`; entre 1 s e 24 h."""
    if not isinstance(text, str) or len(text) > MAX_TEXT_LEN:
        raise InvalidInput("intervalo máximo inválido")
    m = _GAP.fullmatch(text.strip())
    if not m:
        raise InvalidInput("intervalo máximo inválido: use 30s, 5m ou 1h")
    seconds = int(m.group(1)) * _GAP_SECONDS[m.group(2)]
    if not 1 <= seconds <= 86400:
        raise InvalidInput("intervalo máximo fora de 1 s a 24 h")
    return timedelta(seconds=seconds)
