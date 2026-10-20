import shutil
import sys
from pathlib import Path

import pytest

POWERCAP_FAKE = Path(__file__).parent / "fixtures" / "metering" / "powercap_fake"


@pytest.fixture
def copy_powercap_fake():
    """Copia a árvore FAKE do powercap, trocando `_` por `:` nos nomes de zona (`intel-rapl:0`).

    O repositório guarda `intel-rapl_0` porque `:` não faz checkout no Windows; o sysfs real
    (e o provider RAPL) só existem no Linux, então no Windows os testes que dependem dela pulam.
    """

    def copy(dst):
        if sys.platform == "win32":
            pytest.skip("sysfs powercap usa ':' em nomes de diretório, inválido no Windows")
        shutil.copytree(POWERCAP_FAKE, dst)
        for zone in sorted(Path(dst).glob("intel-rapl_*"), key=lambda p: -len(p.name)):
            zone.rename(zone.with_name(zone.name.replace("_", ":")))
        return Path(dst)

    return copy
