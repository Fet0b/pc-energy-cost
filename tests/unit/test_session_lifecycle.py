"""Ciclo de vida de sessões de uso (S1, S2, S3, S4, S6, S7: parte pura de domínio)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from pc_energy_cost.domain.metering.model import ExcludedInterval, Scope
from pc_energy_cost.domain.shared.errors import DomainError, exit_code_for
from pc_energy_cost.domain.usage_session.lifecycle import (
    PROVISIONAL,
    GapKind,
    account_no_reading,
    accumulate_reading,
    add_excluded,
    classify_gap,
    decide_recovery,
    exclusion_seconds,
    resolve_gap,
    summarize,
)
from pc_energy_cost.domain.usage_session.model import (
    Accumulator,
    EndReason,
    EnergyBasis,
    ExportOutcome,
    Session,
    SessionCostSummary,
)

T0 = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
D = Decimal


def _session(**kw) -> Session:
    base = dict(
        id=1, started_at=T0, last_seen_utc=T0, ended_at=None, end_reason=None,
        boot_id="boot-A", sample_interval_s=5, persist_interval_s=60,
        scope=Scope.CPU_PACKAGE, energy_basis=EnergyBasis.MEASURED_COUNTER,
    )
    base.update(kw)
    return Session(**base)


# ---------------------------------------------------------------- S1

def test_s01_closed_session_requires_start_before_end():
    s = _session(ended_at=T0 + timedelta(seconds=10), end_reason=EndReason.USER_STOP)
    assert s.ended_at > s.started_at


def test_s01_open_session_has_no_end_reason():
    assert _session().end_reason is None
    with pytest.raises(DomainError) as e:
        _session(end_reason=EndReason.USER_STOP)
    assert e.value.code == "invalid_input"


def test_s01_closed_session_requires_end_reason():
    with pytest.raises(DomainError) as e:
        _session(ended_at=T0 + timedelta(seconds=1))
    assert e.value.code == "invalid_input"


def test_s01_end_before_start_is_invalid_interval():
    with pytest.raises(DomainError) as e:
        _session(ended_at=T0 - timedelta(seconds=1), end_reason=EndReason.USER_STOP)
    assert e.value.code == "invalid_interval" and e.value.exit_code == 2


def test_s01_new_error_codes_are_exit_2():
    assert exit_code_for("session_already_open") == 2
    assert exit_code_for("session_not_found") == 2


# ---------------------------------------------------------------- S2

def test_s02_same_boot_old_heartbeat_is_crash_recovered():
    s = _session(last_seen_utc=T0 + timedelta(seconds=10))
    now = s.last_seen_utc + timedelta(seconds=2 * 60 + 1)
    d = decide_recovery(s, "boot-A", now)
    assert not d.alive
    assert d.end_reason is EndReason.CRASH_RECOVERED
    assert d.end_at == s.last_seen_utc and d.warning is None


def test_s02_young_heartbeat_same_boot_is_alive():
    s = _session(last_seen_utc=T0)
    d = decide_recovery(s, "boot-A", T0 + timedelta(seconds=2 * 60 - 1))
    assert d.alive and d.end_reason is None and d.end_at is None


def test_s02_exactly_at_limit_is_not_alive():
    d = decide_recovery(_session(), "boot-A", T0 + timedelta(seconds=120))
    assert not d.alive and d.end_reason is EndReason.CRASH_RECOVERED


def test_s02_different_boot_is_reboot_regardless_of_age():
    s = _session(last_seen_utc=T0 + timedelta(seconds=5))
    d = decide_recovery(s, "boot-B", s.last_seen_utc + timedelta(seconds=1))
    assert not d.alive and d.end_reason is EndReason.REBOOT_DETECTED
    assert d.end_at == s.last_seen_utc


def test_s02_missing_boot_id_old_heartbeat_is_crash_with_warning():
    s = _session(boot_id=None, last_seen_utc=T0 + timedelta(seconds=5))
    d = decide_recovery(s, None, s.last_seen_utc + timedelta(hours=1))
    assert d.end_reason is EndReason.CRASH_RECOVERED and d.warning


def test_s02_missing_current_boot_id_also_warns():
    d = decide_recovery(_session(), None, T0 + timedelta(hours=1))
    assert d.end_reason is EndReason.CRASH_RECOVERED and d.warning


def test_s02_last_seen_in_future_is_clock_discontinuity_never_negative():
    s = _session(last_seen_utc=T0 + timedelta(hours=3))
    now = T0 + timedelta(minutes=1)
    d = decide_recovery(s, "boot-A", now)
    assert not d.alive and d.end_reason is EndReason.CLOCK_DISCONTINUITY
    assert d.end_at >= s.started_at and d.end_at <= now


def test_s02_future_even_before_start_clamps_to_start():
    s = _session(last_seen_utc=T0 + timedelta(hours=3))
    d = decide_recovery(s, "boot-A", T0 - timedelta(hours=1))
    assert d.end_at == s.started_at


def test_s02_uses_persist_interval_stored_in_session():
    s = _session(persist_interval_s=10)
    d = decide_recovery(s, "boot-A", T0 + timedelta(seconds=21))
    assert d.end_reason is EndReason.CRASH_RECOVERED


# ---------------------------------------------------------------- S3

def test_s03_wall_clock_goes_back_while_monotonic_advances():
    gap = classify_gap(D("-30"), D("5"), 5)
    assert gap is GapKind.CLOCK_DISCONTINUITY
    res = resolve_gap(gap, T0, D("5"))
    assert res.end_session_at is None and res.end_reason is None
    assert res.excluded == ExcludedInterval(T0, T0 + timedelta(seconds=5), "clock_discontinuity")
    acc = add_excluded(Accumulator(), (res.excluded,))
    assert acc.excluded_s == D("5") and acc.covered_s == 0
    assert acc.measured_wh == 0 and acc.assumed_wh == 0


def test_s03_forward_jump_with_matching_monotonic_is_discontinuity():
    assert classify_gap(D("3600"), D("30"), 5) is GapKind.CLOCK_DISCONTINUITY


def test_s03_consistent_clocks_are_no_gap():
    assert classify_gap(D("5"), D("5"), 5) is GapKind.NONE
    assert classify_gap(D("14"), D("5"), 5) is GapKind.NONE  # dentro de 2 x intervalo


def test_s03_zero_monotonic_span_has_no_excluded_interval():
    res = resolve_gap(GapKind.CLOCK_DISCONTINUITY, T0, D("0"))
    assert res.excluded is None


def test_s03_adapter_reported_exclusion_not_counted_twice():
    reported = (ExcludedInterval(T0, T0 + timedelta(seconds=5), "clock_discontinuity"),)
    mine = (ExcludedInterval(T0, T0 + timedelta(seconds=5), "clock_discontinuity"),)
    assert exclusion_seconds(mine, reported) == 0
    partial = (ExcludedInterval(T0, T0 + timedelta(seconds=8), "gap"),)
    assert exclusion_seconds(partial, reported) == D("3")
    overlapping_new = (
        ExcludedInterval(T0, T0 + timedelta(seconds=4), "gap"),
        ExcludedInterval(T0 + timedelta(seconds=2), T0 + timedelta(seconds=6), "gap"),
    )
    assert exclusion_seconds(overlapping_new, ()) == D("6")
    acc = add_excluded(Accumulator(), partial, already_reported=reported)
    assert acc.excluded_s == D("3")


# ---------------------------------------------------------------- S4

def test_s04_wall_plus_one_hour_monotonic_plus_5s_is_suspend():
    gap = classify_gap(D("3600"), D("5"), 5)
    assert gap is GapKind.SUSPEND
    last_seen = T0 + timedelta(seconds=30)
    res = resolve_gap(gap, last_seen, D("5"))
    assert res.end_reason is EndReason.SUSPEND and res.end_session_at == last_seen
    assert res.excluded is None


def test_s04_suspended_hour_not_in_covered_or_excluded():
    acc = accumulate_reading(Accumulator(), energy_wh=D("1"), duration_s=D("5"))
    after = add_excluded(acc, ())  # suspensão não gera intervalo excluído
    assert after.covered_s == D("5") and after.excluded_s == 0


def test_s04_classification_uses_only_injected_numbers():
    # a classificação é função dos deltas; nenhum relógio real é consultado
    assert classify_gap(D("100"), D("0"), 5) is GapKind.SUSPEND
    assert classify_gap(D("100"), D("10"), 5) is GapKind.SUSPEND  # monotônico <= tolerância


def test_s04_split_is_isolated_in_one_flag(monkeypatch):
    import pc_energy_cost.domain.usage_session.lifecycle as lc

    monkeypatch.setattr(lc, "SUSPEND_SPLITS_SESSION", False)
    res = lc.resolve_gap(GapKind.SUSPEND, T0, D("5"))
    assert res.end_session_at is None and res.end_reason is None


# ---------------------------------------------------------------- S6

def test_s06_stale_sensor_freezes_energy_and_grows_excluded():
    acc = accumulate_reading(Accumulator(), energy_wh=D("2"), duration_s=D("5"))
    stale_after = PROVISIONAL.stale_after_s(5)
    assert stale_after == 15
    acc = account_no_reading(acc, elapsed_s=D("5"), silence_s=D("10"), stale_after_s=stale_after)
    assert acc.excluded_s == 0 and not acc.partial_data  # ainda não obsoleto
    frozen = acc.measured_wh
    acc = account_no_reading(acc, elapsed_s=D("5"), silence_s=D("16"), stale_after_s=stale_after)
    assert acc.stale and acc.partial_data and acc.excluded_s == D("16")
    acc = account_no_reading(acc, elapsed_s=D("5"), silence_s=D("21"), stale_after_s=stale_after)
    assert acc.excluded_s == D("21")
    assert acc.measured_wh == frozen and acc.assumed_wh == 0 and acc.covered_s == D("5")


def test_s06_valid_reading_clears_stale_but_keeps_partial():
    acc = account_no_reading(Accumulator(), D("5"), D("20"), D("15"))
    acc = accumulate_reading(acc, energy_wh=D("1"), duration_s=D("5"))
    assert not acc.stale and acc.partial_data


def test_s06_summary_is_partial():
    acc = account_no_reading(Accumulator(), D("5"), D("20"), D("15"))
    s = _closed_summary(acc)
    assert s.partial_data and s.excluded_s == D("20")


# ---------------------------------------------------------------- S7

def _closed_summary(acc: Accumulator, basis=EnergyBasis.MEASURED_COUNTER) -> SessionCostSummary:
    return summarize(_session(energy_basis=basis, ended_at=T0 + timedelta(minutes=1),
                              end_reason=EndReason.USER_STOP), acc)


def test_s07_measured_only_has_zero_assumed():
    acc = accumulate_reading(Accumulator(), energy_wh=D("1500"), duration_s=D("60"))
    s = _closed_summary(acc)
    assert s.measured_energy_kwh == D("1.5") and s.assumed_energy_kwh == 0
    assert s.energy_basis is EnergyBasis.MEASURED_COUNTER
    assert s.scope is Scope.CPU_PACKAGE


def test_s07_assumed_only_has_zero_measured():
    acc = accumulate_reading(Accumulator(), energy_wh=D("500"), duration_s=D("60"), assumed=True)
    s = _closed_summary(acc, EnergyBasis.USER_POWER)
    assert s.measured_energy_kwh == 0 and s.assumed_energy_kwh == D("0.5")


def test_s07_total_only_exposed_with_parts():
    acc = accumulate_reading(Accumulator(), energy_wh=D("1000"), duration_s=D("60"))
    acc = accumulate_reading(acc, energy_wh=D("500"), duration_s=D("60"), assumed=True)
    s = _closed_summary(acc)
    assert not hasattr(s, "total_energy_kwh")
    assert s.energy_breakdown() == (D("1"), D("0.5"), D("1.5"))


def test_s07_measured_energy_under_assumed_basis_is_rejected():
    acc = accumulate_reading(Accumulator(), energy_wh=D("1"), duration_s=D("1"))
    with pytest.raises(DomainError):
        _closed_summary(acc, EnergyBasis.USER_POWER)


def test_s07_negative_energy_or_duration_rejected():
    with pytest.raises(DomainError):
        accumulate_reading(Accumulator(), energy_wh=D("-1"), duration_s=D("1"))
    with pytest.raises(DomainError):
        accumulate_reading(Accumulator(), energy_wh=D("1"), duration_s=D("-1"))


def test_s07_export_outcome_fields():
    o = ExportOutcome(truncated=True, delivered=False, detail="x")
    assert o.truncated and not o.delivered and o.detail == "x"
