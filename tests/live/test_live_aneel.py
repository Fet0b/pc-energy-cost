"""A51: ANEEL real (marcador `live`; rede real, CSV de tarifas com ~180 MB)."""

from datetime import date
from decimal import Decimal

import pytest

from pc_energy_cost import composition
from pc_energy_cost.application.refresh_catalog import RefreshRequest
from pc_energy_cost.domain.tariff_catalog.model import ELETROPAULO, TariffProfile
from pc_energy_cost.domain.tariff_catalog.selection import select_tariff

pytestmark = pytest.mark.live

# Vigência da fixture (REH 3.596, tarifas_eletropaulo.csv): B1 convencional = 0.78938 R$/kWh
FIXTURE_REH = "RESOLUÇÃO HOMOLOGATÓRIA Nº 3.596, DE 3 DE JULHO DE 2026"
FIXTURE_RATE = Decimal("0.78938")


def test_a51_live_aneel_eletropaulo_b1(tmp_path):
    services = composition.build_services(tmp_path / "store.sqlite", {})
    result = services.refresh(RefreshRequest(force=True))
    assert result.refreshed and not result.stale
    records = services.tariff_source.tariff_records(ELETROPAULO.cnpj)
    day = date.today()
    record = select_tariff(records, TariffProfile(cnpj=ELETROPAULO.cnpj), day)
    if record.reh != FIXTURE_REH:
        pytest.fail(
            "o dataset ANEEL traz outra REH vigente em "
            f"{day.isoformat()}: {record.reh!r} (tusd={record.tusd}, te={record.te}, "
            f"{record.inicio}..{record.fim}); atualizar tests/fixtures/aneel/tarifas_eletropaulo.csv "
            "e esta constante, registrando a diferença"
        )
    assert (record.tusd + record.te) / Decimal(1000) == FIXTURE_RATE
