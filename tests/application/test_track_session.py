"""Caso de uso track_session com fakes e relógios simulados (S2, S4, S5, S6, S7, S8, S10)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from session_fakes import T0, FakeBoot, FakeLedger, FakeMeter, World

from pc_energy_cost.application.resolve_tariff import TariffRequest
from pc_energy_cost.application.track_session import TrackRequest, TrackView, track_session
from pc_energy_cost.domain.metering.model import Scope
from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.domain.usage_session.model import (
    Accumulator,
    EndReason,
    EnergyBasis,
    Session,
)

TARIFF = TariffRequest(manual_total="0,80", inclui=("tributos",))


def run(world, meter, ledger=None, *, stops_after=10, boot="boot-1", on_render=None,
        stop_fn=None, **req):
    ledger = ledger if ledger is not None else FakeLedger()
    request = TrackRequest(tariff=TARIFF, **req)
    result = track_session(
        request, tariff_source=None, meter=meter, ledger=ledger, clock=world, mono=world,
        boot=FakeBoot(boot), sleep=world.sleep,
        should_stop=stop_fn or (lambda: world.sleeps >= stops_after), on_render=on_render,
    )
    return result, ledger


def close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) < Decimal("1e-15")


def code(exc_info) -> str:
    return exc_info.value.code


# ---------------------------------------------------------------- S8

@pytest.mark.parametrize("interval", [0, -1, 3601])
def test_s8_intervalo_fora_dos_limites_e_invalid_input(interval):
    world, ledger = World(), FakeLedger()
    with pytest.raises(DomainError) as e:
        run(world, FakeMeter(world), ledger, sample_interval_s=interval, persist_interval_s=7200)
    assert code(e) == "invalid_input"
    assert ledger.calls == [] and world.sleeps == 0


@pytest.mark.parametrize("interval", [1, 3600])
def test_s8_limites_do_intervalo_sao_aceitos(interval):
    world = World()
    result, _ = run(world, FakeMeter(world), stops_after=1, sample_interval_s=interval,
                    persist_interval_s=interval)
    assert result.end_reason is EndReason.USER_STOP


def test_s8_persistir_menor_que_intervalo_e_invalid_input():
    world, ledger = World(), FakeLedger()
    with pytest.raises(DomainError) as e:
        run(world, FakeMeter(world), ledger, sample_interval_s=10, persist_interval_s=9)
    assert code(e) == "invalid_input"
    assert ledger.calls == []


def test_s8_contagem_exata_de_renderizacoes_e_updates():
    world = World()
    views: list[TrackView] = []
    result, ledger = run(world, FakeMeter(world), stops_after=120, sample_interval_s=5,
                         persist_interval_s=60, on_render=views.append)
    assert len(views) == 120  # uma renderização por intervalo de 5 s em 600 s
    assert ledger.heartbeats == 10  # um UPDATE a cada 60 s
    assert ledger.calls.count("close") == 1
    assert result.session.ended_at == T0 + timedelta(seconds=600)


def test_s8_max_tick_menor_que_intervalo_le_12_vezes_por_renderizacao():
    world = World()
    meter = FakeMeter(world, max_tick="5")
    views: list[TrackView] = []
    result, _ = run(world, meter, stops_after=24, sample_interval_s=60, persist_interval_s=60,
                    on_render=views.append)
    assert len(views) == 2 and meter.ticks == 24
    assert result.acc.excluded_s == 0 and not result.acc.partial_data
    assert result.acc.covered_s == Decimal(120)


def test_s8_intervalo_nao_multiplo_de_max_tick_nunca_le_alem_de_max_tick():
    world = World()
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        world.sleep(seconds)

    views: list[TrackView] = []
    track_session(
        TrackRequest(tariff=TARIFF, sample_interval_s=7, persist_interval_s=60),
        tariff_source=None, meter=FakeMeter(world, max_tick="5"), ledger=FakeLedger(),
        clock=world, mono=world, boot=FakeBoot(), sleep=sleep,
        should_stop=lambda: world.sleeps >= 4, on_render=views.append,
    )
    assert sleeps and all(s <= 5 for s in sleeps)  # 7 s / teto(7/5) = 3,5 s
    assert len(views) == 2  # uma renderização a cada 7 s


# ---------------------------------------------------------------- S7

def test_s7_sensor_medido_so_acumula_medido():
    world = World()
    result, ledger = run(world, FakeMeter(world, power_w="100"), stops_after=60)
    assert close(result.acc.measured_wh, Decimal(100) * 300 / 3600)
    assert result.acc.assumed_wh == 0
    assert result.session.energy_basis is EnergyBasis.MEASURED_COUNTER
    assert result.session.scope is Scope.CPU_PACKAGE
    assert result.end_reason is EndReason.USER_STOP
    assert ledger.sessions[result.session.id].end_reason is EndReason.USER_STOP


def test_s7_potencia_informada_so_acumula_assumido():
    world = World()
    meter = FakeMeter(world)  # ignorado: --potencia sem a flag de completar
    result, _ = run(world, meter, stops_after=60, manual_power_w=Decimal("50"))
    assert result.acc.measured_wh == 0
    assert close(result.acc.assumed_wh, Decimal(50) * 300 / 3600)
    assert result.session.energy_basis is EnergyBasis.USER_POWER
    assert result.session.scope is Scope.MANUAL
    assert meter.ticks == 0


# ---------------------------------------------------------------- S5

def test_s5_sensor_indisponivel_sem_potencia_aborta_sem_criar_sessao():
    world, ledger = World(), FakeLedger()
    with pytest.raises(DomainError) as e:
        run(world, FakeMeter(world, available=False), ledger)
    assert code(e) == "unavailable" and e.value.exit_code == 6
    assert ledger.sessions == {} and "open" not in ledger.calls


def test_s5_sensor_indisponivel_com_potencia_e_flag_vira_assumido():
    world = World()
    result, _ = run(world, FakeMeter(world, available=False), stops_after=12,
                    manual_power_w=Decimal("80"), complete_with_power=True)
    assert result.acc.measured_wh == 0
    assert close(result.acc.assumed_wh, Decimal(80) * 60 / 3600)
    assert result.session.energy_basis is EnergyBasis.USER_POWER


def test_s5_potencia_com_flag_mas_sem_valor_e_invalid_input():
    world = World()
    with pytest.raises(DomainError) as e:
        run(world, FakeMeter(world), complete_with_power=True)
    assert code(e) == "invalid_input"


# ---------------------------------------------------------------- S6

def test_s6_sensor_obsoleto_congela_energia_e_conta_excluido():
    world = World()
    views: list[TrackView] = []
    meter = FakeMeter(world, silent=range(11, 31))  # ticks 11..30 sem leitura
    result, _ = run(world, meter, stops_after=40, on_render=views.append)
    acc = result.acc
    assert acc.partial_data and acc.stale is False  # voltou a ler
    assert acc.excluded_s > 0
    # energia só dos ticks com leitura: nada extrapolado nem preenchido
    assert close(acc.measured_wh, Decimal(100) * acc.covered_s / 3600)
    assert acc.assumed_wh == 0
    stale_views = [v for v in views if v.stale_for_s is not None]
    assert stale_views and all(v.acc.measured_wh == stale_views[0].acc.measured_wh
                               for v in stale_views)


def test_s6_com_flag_completa_o_trecho_sem_leitura_como_assumido():
    world = World()
    meter = FakeMeter(world, silent=range(11, 31))
    result, _ = run(world, meter, stops_after=40, manual_power_w=Decimal("40"),
                    complete_with_power=True)
    acc = result.acc
    assert acc.assumed_wh > 0 and acc.measured_wh > 0
    assert acc.excluded_s == 0  # o trecho foi coberto por potência informada, rotulada assumida


def test_s6_silencio_apos_exclusao_do_adaptador_nao_conta_o_mesmo_tempo_duas_vezes():
    from pc_energy_cost.application.ports import LiveReading
    from pc_energy_cost.domain.metering.model import ExcludedInterval

    class ExcludesThenSilent(FakeMeter):
        def tick(self):
            reading = super().tick()
            if self.ticks == 2:  # o adaptador relata ele mesmo 5 s excluídos
                return LiveReading(excluded=ExcludedInterval(
                    self.world.wall - timedelta(seconds=5), self.world.wall, "gap"))
            return LiveReading() if 3 <= self.ticks <= 6 else reading

    world = World()
    result, _ = run(world, ExcludesThenSilent(world), stops_after=10)
    acc = result.acc
    assert acc.covered_s + acc.excluded_s == Decimal(50)  # 10 tiques de 5 s, nada em dobro
    assert acc.partial_data


# ---------------------------------------------------------------- S4

def test_s4_suspensao_fecha_a_sessao_e_abre_outra_no_retorno():
    world = World()
    world.extra_wall[4] = timedelta(hours=1)  # a parede salta 1 h; o monotônico não
    result, ledger = run(world, FakeMeter(world), stops_after=8)
    first, second = ledger.sessions[1], ledger.sessions[2]
    assert first.end_reason is EndReason.SUSPEND
    assert first.ended_at == T0 + timedelta(seconds=15)  # parede do último tique antes do salto
    assert ledger.accs[1].covered_s == Decimal(15)  # a hora suspensa não entra
    assert second.started_at == T0 + timedelta(hours=1, seconds=20)
    assert result.session.id == 2 and result.end_reason is EndReason.USER_STOP


def test_s3_parede_recuando_vira_intervalo_excluido_sem_energia_negativa():
    world = World()
    world.extra_wall[3] = -timedelta(minutes=10)  # parede recua; o monotônico avança 5 s
    result, ledger = run(world, FakeMeter(world), stops_after=6)
    assert result.acc.excluded_s == Decimal(5) and result.acc.partial_data
    assert result.acc.covered_s == Decimal(25)  # 6 tiques, o do recuo não conta como coberto
    assert result.acc.measured_wh >= 0 and len(ledger.sessions) == 1


# ---------------------------------------------------------------- S2 / S10

def _open_session(last_seen_age_s: int, boot: str | None = "boot-1", persist: int = 60) -> Session:
    return Session(
        id=1, started_at=T0 - timedelta(hours=1),
        last_seen_utc=T0 - timedelta(seconds=last_seen_age_s), ended_at=None, end_reason=None,
        boot_id=boot, sample_interval_s=5, persist_interval_s=persist,
        scope=Scope.CPU_PACKAGE, energy_basis=EnergyBasis.MEASURED_COUNTER,
    )


def test_s2_recupera_sessao_antiga_no_inicio_do_laco():
    world, ledger = World(), FakeLedger()
    ledger.seed(_open_session(last_seen_age_s=500))
    result, _ = run(world, FakeMeter(world), ledger, stops_after=2)
    old = ledger.sessions[1]
    assert old.end_reason is EndReason.CRASH_RECOVERED
    assert old.ended_at == T0 - timedelta(seconds=500)
    assert [s.end_reason for s, _ in result.recovered] == [EndReason.CRASH_RECOVERED]
    assert result.session.id == 2


def test_s2_boot_diferente_vira_reboot_detected():
    world, ledger = World(), FakeLedger()
    ledger.seed(_open_session(last_seen_age_s=10, boot="boot-0"))
    run(world, FakeMeter(world), ledger, stops_after=1)
    assert ledger.sessions[1].end_reason is EndReason.REBOOT_DETECTED


def test_s10_sessao_viva_recusa_sem_fechar_a_primeira():
    world, ledger = World(), FakeLedger()
    ledger.seed(_open_session(last_seen_age_s=30))
    with pytest.raises(DomainError) as e:
        run(world, FakeMeter(world), ledger)
    assert code(e) == "session_already_open" and e.value.exit_code == 2
    assert ledger.sessions[1].is_open and len(ledger.sessions) == 1
    assert world.sleeps == 0


def test_s10_batimento_antigo_e_recuperado():
    world, ledger = World(), FakeLedger()
    ledger.seed(_open_session(last_seen_age_s=121))  # >= 2 x persist (60)
    result, _ = run(world, FakeMeter(world), ledger, stops_after=1)
    assert ledger.sessions[1].end_reason is EndReason.CRASH_RECOVERED
    assert result.session.id == 2


# ---------------------------------------------------------------- encerramento

def test_ctrl_c_encerra_com_user_stop_e_fecha_a_sessao():
    world = World()
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        if calls["n"] == 4:
            raise KeyboardInterrupt
        return False

    result, ledger = run(world, FakeMeter(world), stop_fn=stop)
    assert result.end_reason is EndReason.USER_STOP
    assert ledger.sessions[1].ended_at == T0 + timedelta(seconds=15)
    assert ledger.accs[1].covered_s == Decimal(15)


def test_custo_da_renderizacao_usa_a_tarifa_e_vem_com_as_partes():
    world = World()
    views: list[TrackView] = []
    run(world, FakeMeter(world, power_w="1000"), stops_after=720, on_render=views.append)
    last = views[-1]  # 1000 W por 3600 s = 1 kWh a R$ 0,80
    assert close(last.measured_kwh, Decimal(1)) and last.assumed_kwh == 0
    assert last.cost is not None and last.cost.rounded() == Decimal("0.80")


def test_catalogo_ausente_falha_cedo_sem_abrir_o_ledger():
    world, ledger = World(), FakeLedger()
    request = TrackRequest(tariff=TariffRequest(cnpj="61695227000193"))

    class NoCatalog:
        def tariff_records(self, cnpj):
            raise DomainError("tariff_not_found", "catálogo ausente")

        def source_info(self):
            raise AssertionError

    with pytest.raises(DomainError) as e:
        track_session(
            request, tariff_source=NoCatalog(), meter=FakeMeter(world), ledger=ledger,
            clock=world, mono=world, boot=FakeBoot(), sleep=world.sleep,
        )
    assert code(e) == "tariff_not_found" and ledger.calls == []
