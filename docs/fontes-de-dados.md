# Fontes de dados

Todas vêm do portal de dados abertos da ANEEL via API CKAN
(`https://dadosabertos.aneel.gov.br/api/3/action/package_show?id=<pacote>`). O programa resolve a
URL do CSV pelo `package_show`, validando o resource id e o esquema; se algo mudar, falha de forma
explícita (`schema_mismatch`, `unexpected_html`) e mantém o cache anterior.

| Uso | Pacote CKAN | Resource id | Codificação do CSV |
|---|---|---|---|
| Tarifas homologadas | `tarifas-distribuidoras-energia-eletrica` | `fcf2906c-7c32-4b9b-a637-054e7a5234f4` | UTF-8 (com BOM tolerado) |
| IndQual município (município a conjunto) | `indqual-municipio` | `3f841488-80a8-42f2-a6ca-e0c593b228de` | cp1252 |
| Limites DEC/FEC (conjunto a agente) | `indicadores-coletivos-de-continuidade-dec-e-fec` | `fd69e1dd-fd66-4269-b60c-cc0b7eb221b4` | UTF-8 (com BOM tolerado) |

## Esquemas

- Tarifas (17 colunas, cabeçalho validado): `DatGeracaoConjuntoDados`, `DscREH`, `SigAgente`,
  `NumCNPJDistribuidora`, `DatInicioVigencia`, `DatFimVigencia`, `DscBaseTarifaria`,
  `DscSubGrupo`, `DscModalidadeTarifaria`, `DscClasse`, `DscSubClasse`, `DscDetalhe`,
  `NomPostoTarifario`, `DscUnidadeTerciaria`, `SigAgenteAcessante`, `VlrTUSD`, `VlrTE`.
  Perfil usado: B1, Convencional, Residencial, subclasse Residencial, base "Tarifa de Aplicação",
  unidade MWh. Taxa em R$/kWh = (TUSD + TE) / 1000.
- IndQual (5 colunas) e limites (8 colunas): ver `src/pc_energy_cost/infrastructure/aneel/supplier_csv.py`.
- Fixtures de teste: recortes reais copiados byte a byte em `tests/fixtures/aneel/` (ver o README
  da pasta).

## Observações dos probes (pesquisa de 2026-10-19)

- `Content-Type` observado nos CSVs: `text/csv`, sem `Content-Encoding`; o downloader exige
  `text/csv`, confere `Content-Length` e grava em `.part` antes de promover ao cache.
- O CSV de tarifas tinha cerca de 178 MB na época; o limite do downloader é 300 MiB.
- A capital de São Paulo na fonte de tarifas aparece como `ELETROPAULO` (CNPJ `61695227000193`),
  não "Enel SP". Há linhas duplicadas e variantes (Baixa Renda, SCEE, Base Econômica); só linhas
  totalmente idênticas são deduplicadas, e linhas diferentes no mesmo perfil geram
  `tariff_ambiguous`.
- Existem valores negativos reais de TUSD/TE em outras classes (fixture `tarifas_negativas.csv`);
  são armazenados sem interpretação.
- Cache de arquivo: TTL de 24 h; sem rede, o cache vencido só é usado com
  `--permitir-cache-vencido` (a saída marca `stale` e a idade).
- A proveniência (URL, resource id, `metadata_modified`, `Last-Modified`, hash) fica registrada.
- Pesquisa e proveniência completas: `requirements/research.md`.

## Riscos

1. Dicionário de dados da ANEEL: continua não verificado o significado de `SCEE` e se TUSD/TE de B1
   incluem algo além do componente de energia.
2. A ligação "Enel SP" e `ELETROPAULO` foi verificada pela página oficial da Enel, mas os nomes dos
   municípios atendidos não foram verificados.
5. URLs, resource ids, esquemas e codificações podem mudar; o produto precisa falhar de forma
   explícita (o que a validação de cabeçalho e de `Content-Type` faz).
6. O vínculo município e distribuidora vem de indicadores de qualidade, não de cadastro de
   concessão, e não tem proporção por unidade consumidora; pode haver distribuidora com área
   parcial no município.

(A numeração segue a do plano; os riscos 3 e 4 estão em `docs/telemetria.md`.)
