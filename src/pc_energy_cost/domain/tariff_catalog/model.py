"""Modelo do catálogo de tarifas ANEEL: registros, perfil D4, proveniência e tarifa resolvida."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from ..shared.errors import DomainError, InvalidInput
from ..shared.units import CTX, UnitRateBRLPerKWh

NO_TAXES_WARNING = "sem tributos, bandeiras e encargos fixos"
NOT_APPLICABLE = "Não se aplica"


@dataclass(frozen=True)
class Distributor:
    cnpj: str
    sig_agente: str
    aliases: tuple[str, ...] = ()


ELETROPAULO = Distributor(
    cnpj="61695227000193",
    sig_agente="ELETROPAULO",
    aliases=("Eletropaulo Eletricidade de São Paulo S.A",),
)


@dataclass(frozen=True)
class TariffRecord:
    """Linha do CSV de tarifas (17 colunas); TUSD/TE em R$/MWh; vigência inclusiva."""

    data_geracao: date
    reh: str
    sig_agente: str
    cnpj: str
    inicio: date
    fim: date
    base: str
    subgrupo: str
    modalidade: str
    classe: str
    subclasse: str
    detalhe: str
    posto: str
    unidade: str
    agente_acessante: str
    tusd: Decimal
    te: Decimal

    def __post_init__(self) -> None:
        if self.fim < self.inicio:
            raise InvalidInput("tarifa: vigência com fim anterior ao início")
        for name, value in (("TUSD", self.tusd), ("TE", self.te)):
            if not isinstance(value, Decimal) or not value.is_finite():
                raise InvalidInput(f"tarifa: {name} inválido")

    def covers(self, day: date) -> bool:
        return self.inicio <= day <= self.fim


@dataclass(frozen=True)
class TariffProfile:
    """Perfil D4: B1 residencial convencional, Tarifa de Aplicação, em MWh."""

    cnpj: str
    subgrupo: str = "B1"
    modalidade: str = "Convencional"
    classe: str = "Residencial"
    subclasse: str = "Residencial"
    detalhe: str = NOT_APPLICABLE
    posto: str = NOT_APPLICABLE
    base: str = "Tarifa de Aplicação"
    unidade: str = "MWh"
    agente_acessante: str = NOT_APPLICABLE

    def matches(self, record: TariffRecord) -> bool:
        """Critérios do perfil, sem considerar a data."""
        return (
            record.cnpj == self.cnpj
            and record.subgrupo == self.subgrupo
            and record.modalidade == self.modalidade
            and record.classe == self.classe
            and record.subclasse == self.subclasse
            and record.detalhe == self.detalhe
            and record.posto == self.posto
            and record.base == self.base
            and record.unidade == self.unidade
            and record.agente_acessante == self.agente_acessante
        )

    def criteria(self) -> tuple[tuple[str, str], ...]:
        """Critérios aplicados, com os nomes reais das colunas do CSV."""
        return (
            ("NumCNPJDistribuidora", self.cnpj),
            ("DscSubGrupo", self.subgrupo),
            ("DscModalidadeTarifaria", self.modalidade),
            ("DscClasse", self.classe),
            ("DscSubClasse", self.subclasse),
            ("DscDetalhe", self.detalhe),
            ("NomPostoTarifario", self.posto),
            ("DscBaseTarifaria", self.base),
            ("DscUnidadeTerciaria", self.unidade),
            ("SigAgenteAcessante", self.agente_acessante),
        )


@dataclass(frozen=True)
class SourceInfo:
    """Origem do download do catálogo."""

    url: str
    resource_id: str
    metadata_modified: str
    last_modified: str
    fetched_at: datetime
    sha256: str

    def __post_init__(self) -> None:
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise InvalidInput("proveniência: fetched_at precisa ser UTC")
        if self.fetched_at.utcoffset().total_seconds() != 0:
            raise InvalidInput("proveniência: fetched_at precisa ser UTC")


@dataclass(frozen=True)
class Provenance:
    source: SourceInfo
    data_geracao: date
    reh: str
    inicio: date
    fim: date
    units: str
    criteria: tuple[tuple[str, str], ...]
    warning: str = NO_TAXES_WARNING


@dataclass(frozen=True)
class ResolvedTariff:
    record: TariffRecord
    rate: UnitRateBRLPerKWh
    provenance: Provenance

    @classmethod
    def build(
        cls, record: TariffRecord, profile: TariffProfile, source: SourceInfo
    ) -> ResolvedTariff:
        for name, value in (("TUSD", record.tusd), ("TE", record.te)):
            if value < 0:  # o arquivo real tem créditos negativos; nunca usar na tarifa selecionada
                raise DomainError("schema_mismatch", f"tarifa selecionada: {name} negativo")
        total_mwh = CTX.add(record.tusd, record.te)
        rate = UnitRateBRLPerKWh(CTX.divide(total_mwh, Decimal(1000)))
        provenance = Provenance(
            source=source,
            data_geracao=record.data_geracao,
            reh=record.reh,
            inicio=record.inicio,
            fim=record.fim,
            units=record.unidade,
            criteria=profile.criteria(),
        )
        return cls(record=record, rate=rate, provenance=provenance)
