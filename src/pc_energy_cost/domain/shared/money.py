"""Dinheiro em BRL sobre Decimal; arredondamento HALF_UP a 2 casas só na apresentação e no total (D6)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .errors import InvalidInput
from .units import CTX, KWh, UnitRateBRLPerKWh

_CENT = Decimal("0.01")


def _round2(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP, context=CTX)


@dataclass(frozen=True)
class MoneyBRL:
    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise InvalidInput("dinheiro: esperado Decimal")
        if not self.value.is_finite():
            raise InvalidInput("dinheiro: valor não finito")

    @classmethod
    def of(cls, energy: KWh, rate: UnitRateBRLPerKWh) -> MoneyBRL:
        return cls(CTX.multiply(energy.value, rate.value))

    @classmethod
    def total(cls, parts: Iterable[MoneyBRL]) -> MoneyBRL:
        """Soma sem arredondar e arredonda uma única vez, no total."""
        acc = Decimal(0)
        for part in parts:
            acc = CTX.add(acc, part.value)
        return cls(_round2(acc))

    def rounded(self) -> Decimal:
        return _round2(self.value)

    def display(self) -> str:
        """Formato `R$ 1.234,50`."""
        text = f"{self.rounded():,.2f}"
        text = text.replace(",", "_").replace(".", ",").replace("_", ".")
        return f"R$ {text}"

    def to_json(self) -> str:
        """String decimal com 2 casas e ponto, ex.: `"1234.50"`."""
        return f"{self.rounded():f}"
