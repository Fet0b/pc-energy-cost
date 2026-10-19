"""Value objects de unidades sobre Decimal (contexto de 28 dígitos), limites de D14."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal

from .errors import InvalidInput

CTX = Context(prec=28)

MAX_WATTS = Decimal("100000")
MAX_HOURS = Decimal("87600")
MAX_RATE = Decimal("100")


def _check(value: object, name: str, maximum: Decimal | None, places: int | None) -> Decimal:
    if not isinstance(value, Decimal):
        raise InvalidInput(f"{name}: esperado Decimal")
    if not value.is_finite():
        raise InvalidInput(f"{name}: valor não finito")
    if value < 0:
        raise InvalidInput(f"{name}: valor negativo")
    if maximum is not None and value > maximum:
        raise InvalidInput(f"{name}: acima do limite {maximum}")
    if places is not None and -value.as_tuple().exponent > places:  # type: ignore[operator]
        raise InvalidInput(f"{name}: mais de {places} casas decimais")
    return value


@dataclass(frozen=True)
class Watts:
    value: Decimal

    def __post_init__(self) -> None:
        _check(self.value, "potência (W)", MAX_WATTS, 3)

    def energy_over(self, duration: Duration) -> KWh:
        return KWh(CTX.divide(CTX.multiply(self.value, duration.hours), Decimal(1000)))


@dataclass(frozen=True)
class Duration:
    hours: Decimal

    def __post_init__(self) -> None:
        _check(self.hours, "duração (h)", MAX_HOURS, 4)


@dataclass(frozen=True)
class Wh:
    value: Decimal

    def __post_init__(self) -> None:
        _check(self.value, "energia (Wh)", None, None)

    def to_kwh(self) -> KWh:
        return KWh(CTX.divide(self.value, Decimal(1000)))


@dataclass(frozen=True)
class KWh:
    value: Decimal

    def __post_init__(self) -> None:
        _check(self.value, "energia (kWh)", None, None)

    def display(self) -> str:
        """kWh com 3 casas ROUND_HALF_UP e vírgula; o valor interno não é alterado."""
        rounded = self.value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP, context=CTX)
        return f"{rounded:f}".replace(".", ",")


@dataclass(frozen=True)
class UnitRateBRLPerKWh:
    value: Decimal

    def __post_init__(self) -> None:
        _check(self.value, "tarifa (R$/kWh)", MAX_RATE, 6)
