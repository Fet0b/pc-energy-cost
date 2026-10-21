"""Provider Linux RAPL (escopo `cpu_package`, sempre parcial em relação ao PC).

Somente leitura do sysfs powercap (raiz injetável), sem sudo e sem alterar permissões.
Limites de amostragem/wrap/reset são conservadores, provisórios e não medidos.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from ...domain.metering.model import (
    Available,
    ExcludedInterval,
    Sample,
    SampleUnit,
    Scope,
    Unavailable,
)
from ...domain.shared.errors import InsufficientCoverage, InvalidInput, UnavailableError

DEFAULT_ROOT = Path("/sys/class/powercap")
DEFAULT_P_MAX_W = 1000
MIN_P_MAX_W, MAX_P_MAX_W = 1, 10_000
DT_MAX_FLOOR = Decimal("0.5")
DT_MAX_CEIL = Decimal(60)
SAMPLING_CAP = Decimal(5)
DEFAULT_MEASURE_SECONDS = Decimal(10)  # janela de medição da CLI: provisória, não medida
CLOCK_TOLERANCE_S = Decimal(2)
_TOP = re.compile(r"^intel-rapl:[0-9]+$")
_ZONE = re.compile(r"^intel-rapl:[0-9]+(:[0-9]+)*$")
_PACKAGE = re.compile(r"^package-[0-9]+$")


@dataclass(frozen=True)
class ComponentZone:
    name: str
    path: Path
    scope: Scope = Scope.COMPONENT


@dataclass(frozen=True)
class _Package:
    path: Path
    max_range: int


@dataclass(frozen=True)
class _Reading:
    mono_ns: int
    wall: datetime
    counters: tuple[int, ...]  # um por package, na ordem de `_Package`


class _Fail(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _read_text(path: Path) -> str:
    try:
        return path.read_text().strip()
    except (PermissionError, OSError) as exc:
        raise _Fail("permission_denied") from exc


def _read_int(path: Path) -> int:
    text = _read_text(path)
    if not re.fullmatch(r"[0-9]+|-[0-9]+", text):
        raise _Fail("invalid_counter")
    return int(text)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Nomes públicos para medidores irmãos (ex.: `LiveRaplMeter`); mesmo comportamento dos privados.
CounterReadError = _Fail
read_counter = _read_int
utc_now = _utc_now


class LinuxRaplProvider:
    def __init__(
        self,
        root: Path = DEFAULT_ROOT,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_clock: Callable[[], datetime] = _utc_now,
        max_watts: int = DEFAULT_P_MAX_W,
    ) -> None:
        if (
            isinstance(max_watts, bool)
            or not isinstance(max_watts, int)
            or not MIN_P_MAX_W <= max_watts <= MAX_P_MAX_W
        ):
            raise InvalidInput("--rapl-max-watts deve estar entre 1 e 10000")
        self._root = Path(root)
        self._mono = monotonic_ns
        self._wall = wall_clock
        self._p_max = Decimal(max_watts)
        self._history: list[_Reading] = []
        self._packages_cache: tuple[_Package, ...] | None = None

    # -- zonas -----------------------------------------------------------------
    def _zone_dirs(self) -> list[Path]:
        try:
            return sorted(
                p for p in self._root.iterdir() if p.is_dir() and _ZONE.match(p.name)
            )
        except OSError:
            return []

    def _zone_name(self, path: Path) -> str | None:
        try:
            return (path / "name").read_text().strip()
        except OSError:
            return None

    def _package_dirs(self) -> list[Path]:
        return [
            p for p in self._zone_dirs()
            if _TOP.match(p.name) and _PACKAGE.match(self._zone_name(p) or "")
        ]

    def components(self) -> tuple[ComponentZone, ...]:
        """Zonas listadas e nunca somadas: subzonas e zonas de topo que não são package-N."""
        packages = set(self._package_dirs())
        out = []
        for p in self._zone_dirs():
            if p not in packages:
                out.append(ComponentZone(self._zone_name(p) or p.name, p))
        return tuple(out)

    def _packages(self) -> tuple[_Package, ...]:
        dirs = self._package_dirs()
        if not dirs:
            raise _Fail("no_rapl_zone")
        pkgs = []
        for d in dirs:
            enabled = d / "enabled"
            if enabled.exists() and _read_text(enabled) == "0":
                raise _Fail("zone_disabled")
            max_range = _read_int(d / "max_energy_range_uj")
            _read_int(d / "energy_uj")
            if max_range <= 0:
                raise _Fail("invalid_counter")
            pkgs.append(_Package(d, max_range))
        return tuple(pkgs)

    def availability(self) -> Available | Unavailable:
        try:
            self._packages()
        except _Fail as f:
            return Unavailable(f.reason)
        return Available(Scope.CPU_PACKAGE)

    def _require(self) -> tuple[_Package, ...]:
        try:
            return self._packages()
        except _Fail as f:
            raise UnavailableError(f"telemetria indisponível: {f.reason}") from None

    def require_packages(self) -> tuple[_Package, ...]:
        return self._require()

    def dt_max_for_range(self, max_range: int) -> Decimal:
        return self._dt_max_for(max_range)

    # -- política de amostragem -----------------------------------------------
    def _dt_max_for(self, max_range: int) -> Decimal:
        raw = Decimal(max_range) / (2 * self._p_max * 1_000_000)
        return min(DT_MAX_CEIL, max(DT_MAX_FLOOR, raw))

    @property
    def dt_max_seconds(self) -> Decimal:
        return min(self._dt_max_for(p.max_range) for p in self._require())

    @property
    def sampling_interval_seconds(self) -> Decimal:
        return min(self.dt_max_seconds, SAMPLING_CAP)

    # -- leituras --------------------------------------------------------------
    def take_reading(self) -> None:
        """Lê os contadores agora (relógios monotônico e de parede juntos) e guarda."""
        pkgs = self._require()
        try:
            counters = tuple(_read_int(p.path / "energy_uj") for p in pkgs)
        except _Fail as f:
            raise UnavailableError(f"telemetria indisponível: {f.reason}") from None
        wall = self._wall()
        if wall.tzinfo is None or wall.utcoffset() is None:
            raise InvalidInput("relógio de parede sem fuso")
        self._history.append(_Reading(self._mono(), wall, counters))
        self._packages_cache = pkgs

    def _timeline(self, r: _Reading) -> datetime:
        first = self._history[0]
        return first.wall + timedelta(microseconds=(r.mono_ns - first.mono_ns) // 1000)

    def _analyse(self) -> tuple[list[Sample], list[ExcludedInterval]]:
        samples: list[Sample] = []
        excluded: list[ExcludedInterval] = []
        pkgs = self._packages_cache or ()
        for prev, cur in zip(self._history, self._history[1:]):
            dt = Decimal(cur.mono_ns - prev.mono_ns) / Decimal(1_000_000_000)
            start, end = self._timeline(prev), self._timeline(cur)
            if end <= start:
                continue  # monotônico não avançou: nada a excluir nem a medir
            wall_dt = Decimal((cur.wall - prev.wall).total_seconds())
            reason = None
            if any(dt > self._dt_max_for(p.max_range) for p in pkgs):
                reason = "indeterminate_wrap"
            elif abs(dt - wall_dt) > CLOCK_TOLERANCE_S:
                reason = "clock_discontinuity"
            watts = Decimal(0)
            if reason is None:
                for pkg, a, b in zip(pkgs, prev.counters, cur.counters):
                    delta = b - a if b >= a else b + pkg.max_range - a
                    power = Decimal(delta) / dt / Decimal(1_000_000)
                    if power > self._p_max:
                        reason = "counter_reset_or_invalid"
                        break
                    watts += power
            if reason is not None:
                excluded.append(ExcludedInterval(start, end, reason))
            else:
                samples.append(Sample(start, watts, SampleUnit.WATTS))
        return samples, excluded

    def read(self) -> tuple[Sample, ...]:
        """Potências médias (W) dos pares consecutivos já lidos e válidos; não lê o sysfs."""
        self._require()
        return tuple(self._analyse()[0])

    def excluded_intervals(self) -> tuple[ExcludedInterval, ...]:
        """Intervalos excluídos (para `pre_excluded` de `integrate_power`)."""
        return tuple(self._analyse()[1])

    def window(self) -> tuple[datetime, datetime]:
        """Janela medida: do primeiro ao último par, na linha do tempo monotônica."""
        if len(self._history) < 2:
            raise InvalidInput("RAPL exige ao menos duas leituras", code="invalid_interval")
        return self._timeline(self._history[0]), self._timeline(self._history[-1])


class SamplingRaplMeter:
    """Provider de contador para a CLI: `read()` já amostra (take_reading a cada min(dt_max, 5 s)).

    Envolve `LinuxRaplProvider`; expõe `excluded_intervals()` e `window()` (extensões opcionais
    do MeteringProvider) para que a aplicação os repasse à integração.
    """

    def __init__(
        self,
        provider: LinuxRaplProvider,
        duration_seconds: Decimal = DEFAULT_MEASURE_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if duration_seconds <= 0:
            raise InvalidInput("duração de medição deve ser positiva")
        self._provider = provider
        self._duration = duration_seconds
        self._sleep = sleep

    def availability(self) -> Available | Unavailable:
        return self._provider.availability()

    def read(self) -> tuple[Sample, ...]:
        interval = self._provider.sampling_interval_seconds
        steps = max(1, math.ceil(self._duration / interval))
        self._provider.take_reading()
        for _ in range(steps):
            self._sleep(float(interval))
            self._provider.take_reading()
        samples = self._provider.read()
        if not samples:
            raise InsufficientCoverage(
                "contador RAPL sem nenhum intervalo válido na janela medida", "counter"
            )
        return samples

    def excluded_intervals(self) -> tuple[ExcludedInterval, ...]:
        return self._provider.excluded_intervals()

    def window(self) -> tuple[datetime, datetime]:
        return self._provider.window()
