"""Integração de potência com cobertura (etapa 4): A10-A14 e casos não numerados."""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from pc_energy_cost.domain.energy_estimation.integration import integrate_power
from pc_energy_cost.domain.metering.model import (
    Available,
    ExcludedInterval,
    Sample,
    SampleUnit,
    Scope,
    Unavailable,
)
from pc_energy_cost.domain.shared.errors import DomainError, InsufficientCoverage

SP = ZoneInfo("America/Sao_Paulo")
T0 = datetime(2030, 6, 1, 0, 0, tzinfo=SP)
MIN = timedelta(minutes=1)
HOUR = timedelta(hours=1)


def _s(offset, watts):
    return Sample(T0 + offset, Decimal(str(watts)), SampleUnit.WATTS)


def test_model_types():
    assert Scope.CPU_PACKAGE.value == "cpu_package"
    assert Available(Scope.MANUAL, ()).warnings == ()
    assert Unavailable("permission_denied").reason == "permission_denied"
    with pytest.raises(DomainError):
        ExcludedInterval(T0, T0, "gap")
    with pytest.raises(ValueError):
        ExcludedInterval(T0, T0 + MIN, "bogus")


def test_a10_integracao_csv_com_max_gap_explicito():
    r = integrate_power(
        [_s(0 * HOUR, 100), _s(HOUR, 200), _s(2 * HOUR, 200)],
        T0, T0 + 2 * HOUR, max_gap=HOUR,
    )
    assert r.energy.value == Decimal(300)
    assert r.energy.to_kwh().display() == "0,300"
    assert r.requested_duration == 2 * HOUR
    assert r.coverage_duration == 2 * HOUR
    assert r.excluded_duration == timedelta(0)
    assert r.partial_data is False


def test_a11_default_5min_nao_cobre_amostras_de_1h():
    with pytest.raises(InsufficientCoverage) as e:
        integrate_power(
            [_s(0 * HOUR, 100), _s(HOUR, 200), _s(2 * HOUR, 200)], T0, T0 + 2 * HOUR,
        )
    assert e.value.code == "insufficient_coverage"
    assert e.value.source == "csv"
    assert e.value.exit_code == 2


def test_a12_cobertura_parcial():
    samples = [_s(0 * MIN, 100), _s(5 * MIN, 100), _s(30 * MIN, 100), _s(35 * MIN, 100)]
    r = integrate_power(samples, T0, T0 + 35 * MIN, max_gap=5 * MIN)
    assert r.energy.value == Decimal(100) * Decimal(600) / Decimal(3600)
    assert r.energy.to_kwh().display() == "0,017"
    assert r.coverage_duration == 10 * MIN
    assert r.excluded_duration == 25 * MIN
    assert r.excluded_intervals == (
        ExcludedInterval(T0 + 5 * MIN, T0 + 30 * MIN, "gap"),
    )
    assert r.partial_data is True


def test_a13_zero_coberto_vs_sem_cobertura():
    r = integrate_power(
        [_s(0 * MIN, 0), _s(5 * MIN, 0), _s(10 * MIN, 0)], T0, T0 + 10 * MIN,
    )
    assert r.energy.value == 0
    assert r.coverage_duration == 10 * MIN
    assert r.partial_data is False
    with pytest.raises(InsufficientCoverage):
        integrate_power([_s(0 * HOUR, 0), _s(3 * HOUR, 0)], T0, T0 + 3 * HOUR)
    with pytest.raises(InsufficientCoverage):
        integrate_power([], T0, T0 + HOUR)


def test_a14_duplicata():
    dup = [_s(0 * MIN, 100), _s(0 * MIN, 100), _s(5 * MIN, 100)]
    r = integrate_power(dup, T0, T0 + 5 * MIN)
    assert r.coverage_duration == 5 * MIN
    assert r.energy.value == Decimal(100) * 300 / 3600
    conflict = [_s(0 * MIN, 100), _s(0 * MIN, 101), _s(5 * MIN, 100)]
    with pytest.raises(DomainError) as e:
        integrate_power(conflict, T0, T0 + 5 * MIN)
    assert e.value.code == "csv_conflicting_duplicate"
    assert e.value.exit_code == 2


def test_inicio_antes_da_primeira_amostra_e_no_sample():
    r = integrate_power([_s(10 * MIN, 100), _s(15 * MIN, 100)], T0, T0 + 15 * MIN)
    assert r.excluded_intervals == (ExcludedInterval(T0, T0 + 10 * MIN, "no_sample"),)
    assert r.coverage_duration == 5 * MIN
    assert r.partial_data is True


def test_ultima_amostra_cobre_ate_o_fim_so_dentro_de_max_gap():
    ok = integrate_power([_s(0 * MIN, 100)], T0, T0 + 5 * MIN)
    assert ok.coverage_duration == 5 * MIN and not ok.partial_data
    end = T0 + 5 * MIN + timedelta(seconds=1)
    with pytest.raises(InsufficientCoverage):
        integrate_power([_s(0 * MIN, 100)], T0, end)
    # com outra amostra, só o rabo [último, fim) é excluído
    end = T0 + 10 * MIN + timedelta(seconds=1)
    r = integrate_power([_s(0 * MIN, 100), _s(5 * MIN, 100)], T0, end)
    assert r.coverage_duration == 5 * MIN
    assert r.excluded_intervals == (
        ExcludedInterval(T0 + 5 * MIN, end, "gap"),
    )


def test_amostras_fora_da_janela_sao_recortadas():
    samples = [_s(-2 * MIN, 100), _s(2 * MIN, 200), _s(8 * MIN, 300), _s(30 * MIN, 1)]
    r = integrate_power(samples, T0, T0 + 6 * MIN, max_gap=10 * MIN)
    # [0,2) a 100 W; [2,6) a 200 W
    assert r.energy.value == (Decimal(100) * 120 + Decimal(200) * 240) / 3600
    assert r.coverage_duration == 6 * MIN
    assert r.partial_data is False


def test_trapezio_opt_in():
    samples = [_s(0 * MIN, 100), _s(10 * MIN, 200)]
    steps = integrate_power(samples, T0, T0 + 10 * MIN, max_gap=10 * MIN)
    trap = integrate_power(samples, T0, T0 + 10 * MIN, max_gap=10 * MIN, method="trapezoid")
    assert steps.energy.value == Decimal(100) * 600 / 3600
    assert trap.energy.value == Decimal(150) * 600 / 3600
    with pytest.raises(DomainError):
        integrate_power(samples, T0, T0 + 10 * MIN, method="simpson")


def test_fora_de_ordem_ordena_com_aviso():
    r = integrate_power([_s(5 * MIN, 100), _s(0 * MIN, 100)], T0, T0 + 5 * MIN)
    assert r.coverage_duration == 5 * MIN
    assert "out_of_order" in r.warnings
    ordered = integrate_power([_s(0 * MIN, 100), _s(5 * MIN, 100)], T0, T0 + 5 * MIN)
    assert ordered.warnings == ()


def test_pre_excluded_somado_ao_excluded_duration():
    pre = ExcludedInterval(T0 + 2 * MIN, T0 + 4 * MIN, "counter_reset_or_invalid")
    r = integrate_power(
        [_s(0 * MIN, 100), _s(5 * MIN, 100)], T0, T0 + 5 * MIN, pre_excluded=(pre,),
    )
    assert r.excluded_duration == 2 * MIN
    assert r.coverage_duration == 3 * MIN
    assert r.energy.value == Decimal(100) * 180 / 3600
    assert r.excluded_intervals == (pre,)
    assert r.partial_data is True


@pytest.mark.parametrize(
    "gap", [timedelta(0), timedelta(hours=24, seconds=1), timedelta(milliseconds=999)],
)
def test_max_gap_fora_da_faixa(gap):
    with pytest.raises(DomainError) as e:
        integrate_power([_s(0 * MIN, 1), _s(MIN, 1)], T0, T0 + MIN, max_gap=gap)
    assert e.value.code == "invalid_input"


def test_max_gap_nos_limites_aceitos():
    for gap in (timedelta(seconds=1), timedelta(hours=24)):
        integrate_power([_s(0 * MIN, 1), _s(0 * MIN + gap, 1)], T0, T0 + gap, max_gap=gap)


def test_entradas_invalidas():
    with pytest.raises(DomainError):
        integrate_power([_s(0 * MIN, 1)], T0 + MIN, T0)
    naive = Sample(datetime(2030, 6, 1), Decimal(1), SampleUnit.WATTS)
    with pytest.raises(DomainError):
        integrate_power([naive], T0, T0 + MIN)
    energy = Sample(T0, Decimal(1), SampleUnit.MICROJOULES)
    with pytest.raises(DomainError):
        integrate_power([energy], T0, T0 + MIN)
