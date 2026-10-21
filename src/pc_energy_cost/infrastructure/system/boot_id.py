"""Identificação do boot atual. Sem identificação, devolve None (nunca inventa)."""

from __future__ import annotations

from pathlib import Path

LINUX_BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


class LinuxBootId:
    def __init__(self, path: Path = LINUX_BOOT_ID_PATH) -> None:
        self._path = path

    def current(self) -> str | None:
        try:
            text = self._path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError):
            return None
        return text or None


class NoBootId:
    def current(self) -> str | None:
        return None
