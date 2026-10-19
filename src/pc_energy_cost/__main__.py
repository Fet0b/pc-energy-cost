"""Entrada `python -m pc_energy_cost` e console script `pc-energy-cost`."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from . import composition
from .interface.cli.main import run


def main(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    db_path: Path | None = None,
) -> int:
    """Devolve o código de saída (o console script do setuptools faz `sys.exit(main())`)."""
    env = os.environ if env is None else env
    args = list(sys.argv[1:] if argv is None else argv)
    services = composition.build_services(db_path, env)
    return run(args, services, sys.stdin.isatty())


if __name__ == "__main__":
    sys.exit(main())
