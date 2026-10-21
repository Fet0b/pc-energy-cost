"""Identificação de boot: arquivo falso em tmp_path."""

from pathlib import Path

from pc_energy_cost.application.ports import BootIdentity
from pc_energy_cost.infrastructure.system.boot_id import LinuxBootId, NoBootId


def test_reads_and_strips_boot_id(tmp_path: Path):
    f = tmp_path / "boot_id"
    f.write_text("abc-123\n", encoding="ascii")
    b: BootIdentity = LinuxBootId(f)
    assert b.current() == "abc-123"


def test_missing_file_is_none(tmp_path: Path):
    assert LinuxBootId(tmp_path / "nope").current() is None


def test_unreadable_is_none(tmp_path: Path):
    assert LinuxBootId(tmp_path).current() is None  # diretório: erro de leitura


def test_empty_or_undecodable_is_none(tmp_path: Path):
    f = tmp_path / "boot_id"
    f.write_text("  \n")
    assert LinuxBootId(f).current() is None
    f.write_bytes(b"\xff\xfe\x00")
    assert LinuxBootId(f).current() is None


def test_no_boot_id_is_none():
    assert NoBootId().current() is None
