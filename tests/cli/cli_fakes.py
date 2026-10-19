"""Fakes compartilhados da CLI: tarifas da fixture ANEEL e relógio fixo."""

import csv
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from pc_energy_cost.domain.tariff_catalog.model import SourceInfo, TariffRecord

SP = ZoneInfo("America/Sao_Paulo")
FIXTURE = Path(__file__).parent.parent / "fixtures" / "aneel" / "tarifas_eletropaulo.csv"
CNPJ = "61695227000193"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=SP)
SOURCE = SourceInfo(
    url="https://dadosabertos.aneel.gov.br/api/3/action/package_show?id=tarifas-distribuidoras-energia-eletrica",
    resource_id="fcf2906c-7c32-4b9b-a637-054e7a5234f4",
    metadata_modified="2026-10-18T00:00:00",
    last_modified="Sun, 18 Oct 2026 12:00:00 GMT",
    fetched_at=datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc),
    sha256="0" * 64,
)


def _dec(text: str) -> Decimal:
    return Decimal(text.replace(".", "").replace(",", ".")) if text else Decimal(0)


class FakeTariffSource:
    def __init__(self) -> None:
        with FIXTURE.open(encoding="utf-8", newline="") as fh:
            self.records = [
                TariffRecord(
                    data_geracao=date.fromisoformat(r["DatGeracaoConjuntoDados"]),
                    reh=r["DscREH"], sig_agente=r["SigAgente"], cnpj=r["NumCNPJDistribuidora"],
                    inicio=date.fromisoformat(r["DatInicioVigencia"]),
                    fim=date.fromisoformat(r["DatFimVigencia"]),
                    base=r["DscBaseTarifaria"], subgrupo=r["DscSubGrupo"],
                    modalidade=r["DscModalidadeTarifaria"], classe=r["DscClasse"],
                    subclasse=r["DscSubClasse"], detalhe=r["DscDetalhe"],
                    posto=r["NomPostoTarifario"], unidade=r["DscUnidadeTerciaria"],
                    agente_acessante=r["SigAgenteAcessante"],
                    tusd=_dec(r["VlrTUSD"]), te=_dec(r["VlrTE"]),
                )
                for r in csv.DictReader(fh, delimiter=";")
            ]

    def tariff_records(self, cnpj):
        return [r for r in self.records if r.cnpj == cnpj]

    def source_info(self):
        return SOURCE


class FakeClock:
    def now(self):
        return NOW
