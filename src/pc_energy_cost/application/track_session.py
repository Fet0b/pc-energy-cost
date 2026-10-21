"""Caso de uso: acompanhar uma sessão de uso ao vivo (laço com relógios e sensor injetados).

Uma sessão conta somente enquanto este laço roda; os períodos em que ele está parado são
DESCONHECIDOS (nunca zero, nunca estimados). Nenhum estado cresce com o número de tiques.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal

from ..domain.energy_estimation.schedule import load_zone
from ..domain.metering.model import Available, Scope, Unavailable
from ..domain.shared.errors import DomainError, InvalidInput, UnavailableError
from ..domain.shared.money import MoneyBRL
from ..domain.shared.units import CTX, Watts
from ..domain.usage_session.lifecycle import (
    PROVISIONAL,
    GapKind,
    RecoveryDecision,
    account_no_reading,
    accumulate_reading,
    add_excluded,
    classify_gap,
    decide_recovery,
    resolve_gap,
)
from ..domain.usage_session.model import Accumulator, EndReason, EnergyBasis, Session
from .ports import (
    BootIdentity,
    Clock,
    LiveMeter,
    LiveReading,
    MonotonicClock,
    SessionLedger,
    TariffSource,
)
from .resolve_tariff import TariffRequest, resolve_rate

_NS = Decimal(1_000_000_000)
_US = timedelta(microseconds=1)


@dataclass(frozen=True)
class TrackRequest:
    tariff: TariffRequest
    sample_interval_s: int = PROVISIONAL.sample_interval_s
    persist_interval_s: int = PROVISIONAL.persist_interval_s
    manual_power_w: Decimal | None = None
    complete_with_power: bool = False  # REVIEW-3: preencher com potência só se pedido


@dataclass(frozen=True)
class TrackView:
    """Uma renderização. Energia sempre em partes (medida, assumida); o custo usa a taxa do dia."""

    session_id: int
    at: datetime
    acc: Accumulator
    stale_for_s: Decimal | None  # há quanto tempo sem leitura (None = lendo)
    measured_kwh: Decimal
    assumed_kwh: Decimal
    cost: MoneyBRL | None  # estimativa; None se a tarifa do dia não puder ser resolvida


@dataclass(frozen=True)
class TrackResult:
    session: Session  # a última sessão (uma suspensão divide a sessão)
    acc: Accumulator
    end_reason: EndReason
    recovered: tuple[tuple[Session, RecoveryDecision], ...]
    warnings: tuple[str, ...]


class _AssumedPowerMeter:
    """Potência informada pelo usuário; toda leitura é rotulada `assumed`."""

    def __init__(self, watts: Watts, mono: MonotonicClock) -> None:
        self._w, self._mono = watts.value, mono
        self._last = mono.monotonic_ns()

    def availability(self) -> Available:
        return Available(Scope.MANUAL)

    def max_tick_s(self) -> Decimal:
        return Decimal(PROVISIONAL.max_interval_s)

    def energy_basis(self) -> EnergyBasis:
        return EnergyBasis.USER_POWER

    def tick(self) -> LiveReading:
        now = self._mono.monotonic_ns()
        dur = Decimal(now - self._last) / _NS
        self._last = now
        return LiveReading(energy_wh=CTX.divide(CTX.multiply(self._w, dur), Decimal(3600)),
                           duration_s=dur, assumed=True)


def _validate(request: TrackRequest) -> Watts | None:
    s, p = request.sample_interval_s, request.persist_interval_s
    for name, v in (("--intervalo", s), ("--persistir-a-cada", p)):
        if isinstance(v, bool) or not isinstance(v, int):
            raise InvalidInput(f"{name} deve ser um número inteiro de segundos")
    if not PROVISIONAL.min_interval_s <= s <= PROVISIONAL.max_interval_s:
        raise InvalidInput(
            f"--intervalo fora de [{PROVISIONAL.min_interval_s} s, {PROVISIONAL.max_interval_s} s]"
        )
    if p < s:
        raise InvalidInput("--persistir-a-cada deve ser >= --intervalo")
    watts = Watts(request.manual_power_w) if request.manual_power_w is not None else None
    if request.complete_with_power and watts is None:
        raise InvalidInput("--completar-com-potencia exige a potência informada")
    return watts


def track_session(
    request: TrackRequest,
    *,
    tariff_source: TariffSource | None,
    meter: LiveMeter,
    ledger: SessionLedger,
    clock: Clock,
    mono: MonotonicClock,
    boot: BootIdentity,
    sleep: Callable[[float], None],
    should_stop: Callable[[], bool] = lambda: False,
    on_render: Callable[[TrackView], None] | None = None,
) -> TrackResult:
    watts = _validate(request)  # barato, antes de qualquer I/O
    selection = resolve_rate(request.tariff, tariff_source)  # type: ignore[arg-type]
    zone = load_zone()

    def cost_for(kwh: Decimal, at: datetime) -> MoneyBRL | None:
        try:
            window = selection.lookup(at.astimezone(zone).date())
        except DomainError:
            return None
        return MoneyBRL(CTX.multiply(kwh, CTX.add(window.rate.value, selection.extras.adicional.value)))

    selection.lookup(clock.now().astimezone(zone).date())  # tarifa ausente falha cedo, antes de abrir o ledger

    assumed = _AssumedPowerMeter(watts, mono) if watts is not None else None
    active: LiveMeter
    if assumed is not None and not request.complete_with_power:
        active = assumed
    else:
        availability = meter.availability()
        if isinstance(availability, Unavailable):
            if assumed is None:
                raise UnavailableError(f"telemetria indisponível: {availability.reason}")
            active = assumed
        else:
            active = meter
    scope = active.availability().scope
    basis = active.energy_basis()
    fill = assumed is not None and request.complete_with_power

    sample = request.sample_interval_s
    max_tick = active.max_tick_s()
    if max_tick <= 0:
        raise InvalidInput("medidor com max_tick_s não positivo")
    # leituras por renderização: teto de sample/max_tick (o `//` de Decimal trunca para zero)
    per_render = max(1, int((Decimal(sample) / max_tick).to_integral_value(rounding=ROUND_CEILING)))
    tick_s = Decimal(sample) / per_render  # <= max_tick e divide o intervalo exatamente
    per_persist = max(per_render, request.persist_interval_s * per_render // sample)
    stale_after = PROVISIONAL.stale_after_s(sample)

    now = clock.now()
    boot_now = boot.current()
    recovered: list[tuple[Session, RecoveryDecision]] = []
    warnings: list[str] = []
    found = ledger.recover_open(lambda s: decide_recovery(s, boot_now, now))
    if found is not None:
        old, decision, _ = found
        if decision.alive:
            raise DomainError(
                "session_already_open",
                f"já existe uma sessão aberta e viva (id {old.id}); ela não foi alterada",
            )
        recovered.append((old, decision))
        if decision.warning:
            warnings.append(decision.warning)

    def open_at(at: datetime) -> Session:
        return ledger.open_session(
            started_at=at, boot_id=boot_now, sample_interval_s=sample,
            persist_interval_s=request.persist_interval_s, scope=scope, energy_basis=basis,
        )

    session = open_at(now)
    acc = Accumulator()
    prev_wall, prev_mono = now, mono.monotonic_ns()
    last_valid = prev_mono
    accounted = prev_mono  # fim do último tempo já contado (coberto ou excluído)
    tick_i = 0

    try:
        while not should_stop():
            sleep(float(tick_s))
            tick_i += 1
            wall, mono_ns = clock.now(), mono.monotonic_ns()
            wall_delta = Decimal((wall - prev_wall) // _US) / Decimal(1_000_000)
            mono_delta = Decimal(mono_ns - prev_mono) / _NS
            kind = classify_gap(wall_delta, mono_delta, sample)
            reading = active.tick()  # sempre consumido: o medidor mantém só a leitura anterior
            if kind is not GapKind.NONE:
                gap = resolve_gap(kind, prev_wall, mono_delta)
                if gap.end_session_at is not None and gap.end_reason is not None:
                    ledger.close(session.id, max(gap.end_session_at, session.started_at),
                                 gap.end_reason, acc)
                    session, acc = open_at(wall), Accumulator()
                    last_valid = mono_ns
                elif gap.excluded is not None:
                    acc = add_excluded(acc, [gap.excluded])
                accounted = mono_ns
                # a leitura que atravessa a lacuna é descartada: nada de tempo duplicado
            elif reading.excluded is not None:
                acc = add_excluded(acc, [reading.excluded])
                accounted = mono_ns
            elif reading.duration_s > 0:
                acc = accumulate_reading(acc, energy_wh=reading.energy_wh,
                                         duration_s=reading.duration_s, assumed=reading.assumed)
                last_valid = accounted = mono_ns
            elif fill:
                assert watts is not None
                energy = CTX.divide(CTX.multiply(watts.value, mono_delta), Decimal(3600))
                acc = accumulate_reading(acc, energy_wh=energy, duration_s=mono_delta, assumed=True)
                last_valid = accounted = mono_ns
            else:
                # silêncio conta só o tempo ainda não contado (exclusões já relatadas ficam fora)
                silence = Decimal(mono_ns - accounted) / _NS
                acc = account_no_reading(acc, mono_delta, silence, stale_after)
            prev_wall, prev_mono = wall, mono_ns

            if tick_i % per_persist == 0:
                ledger.heartbeat(session.id, wall, acc)
            if on_render is not None and tick_i % per_render == 0:
                m_kwh, a_kwh = acc.measured_wh / 1000, acc.assumed_wh / 1000
                stale_for = Decimal(mono_ns - last_valid) / _NS if acc.stale else None
                on_render(TrackView(session.id, wall, acc, stale_for, m_kwh, a_kwh,
                                    cost_for(m_kwh + a_kwh, wall)))
    except KeyboardInterrupt:
        pass
    # Outras exceções propagam sem fechar: a sessão fica aberta e a recuperação a classifica.
    ended = max(clock.now(), session.started_at)
    closed = ledger.close(session.id, ended, EndReason.USER_STOP, acc)
    return TrackResult(closed, acc, EndReason.USER_STOP, tuple(recovered), tuple(warnings))
