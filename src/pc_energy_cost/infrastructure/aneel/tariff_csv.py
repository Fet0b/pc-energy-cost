"""Parser streaming do CSV de tarifas homologadas (17 colunas, `utf-8-sig`)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

from ...domain.shared.errors import DomainError, InvalidInput
from ...domain.shared.parsing import parse_decimal
from ...domain.tariff_catalog.model import TariffRecord
from .csv_common import check_header as _check
from .csv_common import iter_rows, mismatch

ENCODING = "utf-8-sig"
EXPECTED_COLUMNS: tuple[str, ...] = (
    "DatGeracaoConjuntoDados", "DscREH", "SigAgente", "NumCNPJDistribuidora",
    "DatInicioVigencia", "DatFimVigencia", "DscBaseTarifaria", "DscSubGrupo",
    "DscModalidadeTarifaria", "DscClasse", "DscSubClasse", "DscDetalhe",
    "NomPostoTarifario", "DscUnidadeTerciaria", "SigAgenteAcessante", "VlrTUSD", "VlrTE",
)


def parse_tariff_decimal(text: str) -> Decimal:
    """Decimal pt-BR; aceita as formas ANEEL `,00` (sem parte inteira) e `-,69`/`-7,53`.

    O arquivo real traz valores negativos (créditos, ex.: SCEE/Tarifa Social) fora do perfil
    B1 convencional; o sinal é preservado (sem reinterpretar) e a rejeição de componente
    negativo acontece só ao resolver a tarifa selecionada (`ResolvedTariff.build`)."""
    text = text.strip()
    negative = text.startswith("-")
    if negative:
        text = text[1:]
        if text[:1].isspace():
            raise InvalidInput("número inválido")
    if text.startswith(","):
        text = "0" + text
    value = parse_decimal(text)
    return -value if negative else value


def check_header(path: Path) -> None:
    _check(path, EXPECTED_COLUMNS, ENCODING, "tarifas")


def read_tariffs(path: Path) -> Iterator[TariffRecord]:
    for row in iter_rows(path, EXPECTED_COLUMNS, ENCODING, "tarifas"):
        try:
            yield TariffRecord(
                data_geracao=date.fromisoformat(row["DatGeracaoConjuntoDados"]),
                reh=row["DscREH"],
                sig_agente=row["SigAgente"],
                cnpj=row["NumCNPJDistribuidora"],
                inicio=date.fromisoformat(row["DatInicioVigencia"]),
                fim=date.fromisoformat(row["DatFimVigencia"]),
                base=row["DscBaseTarifaria"],
                subgrupo=row["DscSubGrupo"],
                modalidade=row["DscModalidadeTarifaria"],
                classe=row["DscClasse"],
                subclasse=row["DscSubClasse"],
                detalhe=row["DscDetalhe"],
                posto=row["NomPostoTarifario"],
                unidade=row["DscUnidadeTerciaria"],
                agente_acessante=row["SigAgenteAcessante"],
                tusd=parse_tariff_decimal(row["VlrTUSD"]),
                te=parse_tariff_decimal(row["VlrTE"]),
            )
        except (ValueError, DomainError) as exc:
            raise mismatch(f"tarifas: linha inválida ({exc})") from exc
