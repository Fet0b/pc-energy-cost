"""Agenda e fuso (etapa 3): A9, A49 e casos não numerados."""

import io
import struct
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from pc_energy_cost.domain.energy_estimation.schedule import (
    ZONE_NAME,
    Interval,
    Schedule,
    load_zone,
)
from pc_energy_cost.domain.shared.errors import DomainError
from pc_energy_cost.domain.shared.units import Duration

SP = ZoneInfo("America/Sao_Paulo")


def _dt(h, d=1, mo=6, y=2030, tz=SP):
    return datetime(y, mo, d, h, 0, tzinfo=tz)


def _fictitious_dst_zone() -> ZoneInfo:
    """Fuso FICTÍCIO (bytes TZif v1 gerados aqui, sem fixture): -03:00 padrão,
    -02:00 de verão a partir de 2030-06-01 03:00 UTC (sem volta)."""
    transition = int(datetime(2030, 6, 1, 3, tzinfo=timezone.utc).timestamp())
    chars = b"STD\0DST\0"
    types = struct.pack(">lBB", -3 * 3600, 0, 0) + struct.pack(">lBB", -2 * 3600, 1, 4)
    header = b"TZif" + b"\0" + b"\0" * 15
    header += struct.pack(">6l", 0, 0, 0, 1, 2, len(chars))
    body = struct.pack(">l", transition) + bytes([1]) + types + chars
    return ZoneInfo.from_file(io.BytesIO(header + body), key="Ficticio/Dst")


def test_a09_schedule_adjacent_valid_and_overlap_rejected():
    ok = Schedule([Interval(_dt(8), _dt(12)), Interval(_dt(12), _dt(13))])
    assert ok.total_duration() == Duration(Decimal("5"))
    with pytest.raises(DomainError) as exc:
        Schedule([Interval(_dt(8), _dt(12)), Interval(_dt(11), _dt(13))])
    assert exc.value.code == "overlapping_intervals"
    # ordem de entrada não importa
    with pytest.raises(DomainError) as exc:
        Schedule([Interval(_dt(11), _dt(13)), Interval(_dt(8), _dt(12))])
    assert exc.value.code == "overlapping_intervals"


def test_a49_missing_timezone_data_is_domain_error():
    def broken(key):
        raise ZoneInfoNotFoundError(key)

    with pytest.raises(DomainError) as exc:
        load_zone(broken)
    assert exc.value.code == "timezone_data_missing"
    assert exc.value.exit_code == 2


def test_load_zone_default_is_sao_paulo():
    assert load_zone().key == ZONE_NAME == "America/Sao_Paulo"


@pytest.mark.parametrize("end_hour", [8, 7])
def test_interval_end_not_after_start_is_invalid(end_hour):
    with pytest.raises(DomainError) as exc:
        Interval(_dt(8), _dt(end_hour))
    assert exc.value.code == "invalid_interval"


def test_duration_on_dst_day_uses_zone_not_fixed_24h():
    zone = _fictitious_dst_zone()
    naive = Interval(datetime(2030, 6, 1, 0, 0), datetime(2030, 6, 2, 0, 0), zone=zone)
    assert naive.duration() == Duration(Decimal("23"))
    assert Schedule([naive]).total_duration() == Duration(Decimal("23"))


def test_naive_is_interpreted_in_sao_paulo():
    iv = Interval(datetime(2026, 1, 10, 8), datetime(2026, 1, 10, 9))
    assert iv.start.utcoffset() == timedelta(hours=-3)
    assert iv.start.tzinfo.key == "America/Sao_Paulo"


def test_explicit_offset_is_respected():
    utc = timezone.utc
    iv = Interval(datetime(2026, 1, 10, 11, tzinfo=utc), datetime(2026, 1, 10, 12, tzinfo=utc))
    assert iv.start.utcoffset() == timedelta(0)
    assert iv.duration() == Duration(Decimal("1"))
