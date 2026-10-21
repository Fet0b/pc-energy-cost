"""Fakes em memória para os casos de uso de sessão (relógios, medidor, ledger, exportador)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from pc_energy_cost.domain.metering.model import Available, Scope, Unavailable
from pc_energy_cost.domain.usage_session.lifecycle import RecoveryDecision
from pc_energy_cost.domain.usage_session.model import (
    Accumulator,
    EndReason,
    EnergyBasis,
    ExportOutcome,
    Session,
    SessionCostSummary,
)
from pc_energy_cost.application.ports import LiveReading

T0 = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


class World:
    """Tempo simulado: parede e monotônico independentes; `sleep` avança os dois."""

    def __init__(self, start: datetime = T0) -> None:
        self.wall = start
        self.mono_ns = 0
        self.sleeps = 0
        self.extra_wall: dict[int, timedelta] = {}  # sleep nº N -> salto só da parede

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.wall += timedelta(seconds=seconds) + self.extra_wall.get(self.sleeps, timedelta(0))
        self.mono_ns += int(seconds * 1_000_000_000)

    def now(self) -> datetime:
        return self.wall

    def monotonic_ns(self) -> int:
        return self.mono_ns


class FakeBoot:
    def __init__(self, boot_id: str | None = "boot-1") -> None:
        self.boot_id = boot_id

    def current(self) -> str | None:
        return self.boot_id


class FakeMeter:
    """Potência constante `power_w`; ticks em `silent` devolvem leitura vazia (sem leitura)."""

    def __init__(
        self, world: World, power_w: str = "100", max_tick: str = "5",
        available: bool = True, silent: range = range(0),
        basis: EnergyBasis = EnergyBasis.MEASURED_COUNTER,
        scope: Scope = Scope.CPU_PACKAGE,
    ) -> None:
        self.world, self.power_w = world, Decimal(power_w)
        self._max_tick, self.available, self.silent = Decimal(max_tick), available, silent
        self._basis, self.scope = basis, scope
        self.ticks = 0
        self._last = world.mono_ns

    def availability(self) -> Available | Unavailable:
        return Available(self.scope) if self.available else Unavailable("sem sensor")

    def max_tick_s(self) -> Decimal:
        return self._max_tick

    def energy_basis(self) -> EnergyBasis:
        return self._basis

    def tick(self) -> LiveReading:
        self.ticks += 1
        dur = Decimal(self.world.mono_ns - self._last) / Decimal(1_000_000_000)
        self._last = self.world.mono_ns
        if self.ticks in self.silent:
            return LiveReading()
        return LiveReading(energy_wh=self.power_w * dur / 3600, duration_s=dur)


class FakeLedger:
    def __init__(self) -> None:
        self.sessions: dict[int, Session] = {}
        self.accs: dict[int, Accumulator] = {}
        self.heartbeats = 0
        self.calls: list[str] = []

    def seed(self, session: Session, acc: Accumulator = Accumulator()) -> None:
        self.sessions[session.id] = session
        self.accs[session.id] = acc

    def open_session(
        self, *, started_at: datetime, boot_id: str | None, sample_interval_s: int,
        persist_interval_s: int, scope: Scope, energy_basis: EnergyBasis,
    ) -> Session:
        self.calls.append("open")
        sid = max(self.sessions, default=0) + 1
        s = Session(sid, started_at, started_at, None, None, boot_id, sample_interval_s,
                    persist_interval_s, scope, energy_basis)
        self.seed(s)
        return s

    def heartbeat(self, session_id: int, last_seen_utc: datetime, acc: Accumulator) -> None:
        self.heartbeats += 1
        self.sessions[session_id] = replace(self.sessions[session_id], last_seen_utc=last_seen_utc)
        self.accs[session_id] = acc

    def close(
        self, session_id: int, ended_at: datetime, end_reason: EndReason, acc: Accumulator
    ) -> Session:
        self.calls.append("close")
        s = replace(self.sessions[session_id], ended_at=ended_at, end_reason=end_reason,
                    last_seen_utc=ended_at)
        self.sessions[session_id], self.accs[session_id] = s, acc
        return s

    def recover_open(
        self, decide: Callable[[Session], RecoveryDecision]
    ) -> tuple[Session, RecoveryDecision, Accumulator] | None:
        self.calls.append("recover")
        for s in self.sessions.values():
            if s.is_open:
                d = decide(s)
                if not d.alive:
                    assert d.end_reason is not None and d.end_at is not None
                    s = self.close(s.id, d.end_at, d.end_reason, self.accs[s.id])
                return s, d, self.accs[s.id]
        return None

    def list_sessions(self, since: datetime | None = None, until: datetime | None = None):
        return [
            (s, self.accs[s.id]) for s in self.sessions.values()
            if (since is None or (s.ended_at or s.last_seen_utc) > since)
            and (until is None or s.started_at < until)
        ]

    def get(self, session_id: int):
        s = self.sessions.get(session_id)
        return None if s is None else (s, self.accs[session_id])


class FakeExporter:
    def __init__(self) -> None:
        self.received: list[SessionCostSummary] = []

    def export(self, summary: SessionCostSummary) -> ExportOutcome:
        self.received.append(summary)
        return ExportOutcome(truncated=False, delivered=True)
