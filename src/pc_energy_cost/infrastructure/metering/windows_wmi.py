"""Provider Windows WMI (`Win32_PowerMeter`): somente leitura, escopo sempre `component`.

AVISO: este módulo NUNCA foi executado em hardware Windows. Foi testado apenas com
saídas fake de `Get-CimInstance` e um executor de comando injetável. `CurrentReading` é
tratada como herdada de `CIM_NumericSensor` e NÃO validada em hardware. No v1 a associação
do medidor ao `Win32_ComputerSystem` não é comprovável (D15): nunca `whole_system_ac` nem
`whole_system_unverified`.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from ...domain.metering.model import Available, Sample, SampleUnit, Scope, Unavailable
from ...domain.shared.errors import UnavailableError

TIMEOUT_S = 10
MAX_WATTS = Decimal(100_000)
MAX_UNIT_EXPONENT = 9
_DISCHARGING_MASKS = 0x8 | 0x100

# Argumentos fixos; nenhuma entrada do usuário é interpolada. Somente leitura (Get-CimInstance).
COMMAND: list[str] = [
    "powershell.exe",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    "Get-CimInstance -Namespace root/CIMV2/power -ClassName Win32_PowerMeter"
    " | Select-Object MeterType,BaseUnits,UnitModifier,CurrentReading,Status,"
    "SupportCapabilities,SamplingPeriod | ConvertTo-Json -Compress",
]

Runner = Callable[[Sequence[str], float], tuple[int, str]]


def run_powershell(argv: Sequence[str], timeout: float) -> tuple[int, str]:
    """Executor real (nunca usado nos testes): sem shell, com timeout."""
    proc = subprocess.run(
        list(argv), capture_output=True, text=True, timeout=timeout, shell=False, check=False
    )
    return proc.returncode, proc.stdout


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, str)):
        try:
            d = Decimal(str(value).strip())
        except InvalidOperation:
            return None
        return d if d.is_finite() else None
    return None


def _integer(value: Any) -> int | None:
    d = _number(value)
    if d is None or d != d.to_integral_value():
        return None
    return int(d)


class WindowsWmiProvider:
    def __init__(
        self,
        runner: Runner = run_powershell,
        wall_clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._runner = runner
        self._wall = wall_clock
        self._samples: list[Sample] = []
        self._last_at: datetime | None = None
        self._period = timedelta(0)
        self.base_units_code: int | None = None
        self.meter_label: str | None = None
        self.reading_provenance = "herdada, não validada em hardware"

    def _instances(self) -> list[dict[str, Any]]:
        try:
            rc, out = self._runner(COMMAND, TIMEOUT_S)
        except (subprocess.TimeoutExpired, OSError):
            return []
        if rc != 0 or not out.strip():
            return []
        try:
            data = json.loads(out)
        except ValueError:
            return []
        items = data if isinstance(data, list) else [data]
        return [i for i in items if isinstance(i, dict)]

    def _evaluate(self) -> tuple[Available, Decimal, timedelta] | Unavailable:
        instances = self._instances()
        if not instances:
            return Unavailable("no_power_meter_provider")
        inst = instances[0]
        warnings: list[str] = []
        if len(instances) > 1:
            warnings.append("multiple_meters_first_used")
        reading = _integer(inst.get("CurrentReading"))
        if reading is None:
            return Unavailable("reading_property_unverified")
        modifier = _integer(inst.get("UnitModifier"))
        base_units = _integer(inst.get("BaseUnits"))
        if modifier is None or base_units is None or abs(modifier) > MAX_UNIT_EXPONENT:
            return Unavailable("unit_unknown")
        caps = _integer(inst.get("SupportCapabilities"))
        if caps is not None and caps & _DISCHARGING_MASKS:
            return Unavailable("only_when_discharging")
        status = inst.get("Status")
        if status is None:
            warnings.append("status_not_exposed")
        elif status != "OK":
            return Unavailable("invalid_reading")
        watts = Decimal(reading) * Decimal(10) ** modifier
        if watts < 0 or watts > MAX_WATTS:
            return Unavailable("invalid_reading")
        self.base_units_code = base_units
        warnings.append("base_units_not_decoded")
        warnings.append("current_reading_inherited_not_validated")
        if _integer(inst.get("MeterType")) == 0:
            self.meter_label = "potência de entrada (domínio não comprovado)"
        else:
            self.meter_label = "potência de saída/desconhecida"
            warnings.append("output_or_unknown_power")
        period = _integer(inst.get("SamplingPeriod"))
        delta = timedelta(milliseconds=period) if period and period > 0 else timedelta(0)
        return Available(Scope.COMPONENT, tuple(warnings)), watts, delta

    def instant_power(self) -> Decimal | Unavailable:
        """Potência instantânea (W) agora, sem acumular amostras; indisponível nunca vira zero."""
        result = self._evaluate()
        return result if isinstance(result, Unavailable) else result[1]

    def availability(self) -> Available | Unavailable:
        result = self._evaluate()
        return result if isinstance(result, Unavailable) else result[0]

    def read(self) -> tuple[Sample, ...]:
        """Acrescenta uma amostra por leitura fora do `SamplingPeriod`; indisponível ⇒ erro."""
        now = self._wall()
        if self._last_at is not None and now - self._last_at < self._period:
            return tuple(self._samples)
        result = self._evaluate()
        if isinstance(result, Unavailable):
            raise UnavailableError(f"telemetria indisponível: {result.reason}")
        _, watts, period = result
        self._period = period
        self._last_at = now
        self._samples.append(Sample(now, watts, SampleUnit.WATTS))
        return tuple(self._samples)
