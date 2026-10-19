# Pesquisa e probes (fase de planejamento)

Todos os probes foram feitos pelo orquestrador (Bash + `python3 -I` stdlib `urllib`/`csv`), somente leitura, fora do produto. Logs brutos, downloads e scripts ficam FORA do repositório em `diretório privado de planejamento (fora do repositório)/` (`probes/`, `scripts/`, `evidence/`). Conteúdo externo foi tratado como dados, nunca como instruções. Nada aqui é teste do programa final: são provas de viabilidade.

## Relógio e datas

- Data de contexto pedida: 2026-10-19. Relógio local (`date -u`) no início: `Mon Oct 19 04:06:39 UTC 2026`; cabeçalho HTTP `Date` dos servidores ANEEL: `Mon, 19 Oct 2026 04:07:12 GMT`. Sem divergência relevante. Todos os `fetched_at` abaixo são UTC reais registrados nos logs.
- O ambiente é Linux (`Linux-7.0.14-23-pve-x86_64`, Python 3.12.3, uid 1000). Nada foi testado em Windows.

## 1. ANEEL — tarifas homologadas (CKAN)

- `package_show?id=tarifas-distribuidoras-energia-eletrica` → HTTP 200, 8617 B, sha256 `82bc609d…8805228`, fetched_at 2026-10-19T04:07:02Z, `metadata_modified` 2026-10-18T10:06:25. Log: `probes/probe1.log`, corpo `probes/pkg_tarifas.json`.
- Dataset id `5a583f3e-1646-4f67-bf0f-69db4203e89e`. Recursos: CSV `fcf2906c-7c32-4b9b-a637-054e7a5234f4` (178 230 008 B, last_modified 2026-10-18T10:02:24), XML (644 MB), PARQUET (2,6 MB), PDF dicionário `2d3478e0-8aa0-4cd4-81a7-5f8967cd8804`.
- CSV baixado inteiro (viável: 178 MB, ~3 s): HTTP 200, sha256 `140062392e44e7aec910a598db4e149341774a945272e88702c42db20ff60c80`, fetched_at 2026-10-19T04:07:12Z, `Content-Type: text/csv`, sem `Content-Encoding`. Log: `probes/probe2.log`.
- Formato: `;` como separador, tudo entre aspas, UTF-8 SEM BOM (correção: o primeiro byte observado é `"`; `utf-8-sig` decodifica do mesmo jeito; latin-1 também "funciona" mas gera mojibake), decimal com vírgula (`472,42`, e `,00` sem zero à esquerda), datas ISO `YYYY-MM-DD`. 655 289 linhas de dados, 115 CNPJs distintos, `DatGeracaoConjuntoDados` = 2026-10-18 em todas.
- Header real (17 colunas): `DatGeracaoConjuntoDados;DscREH;SigAgente;NumCNPJDistribuidora;DatInicioVigencia;DatFimVigencia;DscBaseTarifaria;DscSubGrupo;DscModalidadeTarifaria;DscClasse;DscSubClasse;DscDetalhe;NomPostoTarifario;DscUnidadeTerciaria;SigAgenteAcessante;VlrTUSD;VlrTE`.
- Domínios observados (log `probe3.log`): `DscBaseTarifaria` ∈ {Base Econômica, Tarifa de Aplicação}; `DscSubGrupo` 13 valores incl. B1; `DscModalidadeTarifaria` 14 valores incl. Convencional, Branca, `Convencional pré-pagamento`; `DscClasse` ∈ {Não se aplica, Residencial, Rural, Iluminação pública}; `DscSubClasse` 11 valores (Residencial, Baixa Renda, Residencial Tarifa Social – faixa 01/02, Residencial Desconto Social – faixa 01/02…); `DscDetalhe` ∈ {Não se aplica, SCEE, APE, TIPO 01/02, …}; `NomPostoTarifario` 8 valores; `DscUnidadeTerciaria` ∈ {kW, MWh}.
- **ENEL SP no dataset**: o `SigAgente` é `ELETROPAULO`, CNPJ `61695227000193` (9 530 linhas). NÃO existe linha com `SigAgente` "ENEL SP"; outras Enel (`ENEL CE`, `ENEL RJ`) são outros CNPJs. **Atualização (probe suplementar, 2026-10-19T04:20:57Z, `probes/supplement-probe.json`, HTML original `probes/enel_alias.html`):** a página oficial `https://www.enel.com.br/pt-saopaulo/golpes-e-fraudes.html` (GET HTTP 200, sha256 `0cd71d7ebacbb062fb7ea2d0c3bc4449624c67b84574be9b603c3b8e915a4d45`, Last-Modified 2026-10-16) diz, no contexto "esteja sempre atento ao CNPJ da Enel": `Eletropaulo Eletricidade de São Paulo S.A - CNPJ: 61.695.227/0001-93`. Isso liga o CNPJ `61695227000193` (chave do dataset ANEEL, `SigAgente=ELETROPAULO`) à Enel São Paulo em fonte oficial da própria Enel: o alias "Enel SP" ↔ `ELETROPAULO` está **verificado por evidência** para o CNPJ. Continuam sem verificação os nomes dos 24 municípios.
- **Vigências ENEL SP (dataset completo)**: últimas seis: 2022-07-04→2023-07-03; 2023-07-04→2024-07-03; 2024-07-04→2025-07-03; 2025-07-04→2025-12-31 e 2026-01-01→2026-07-03 (ambas REH 3.477/2025: período partido no 31/12); **2026-07-04→2027-07-03, REH 3.596 de 3 jul 2026 (máx. `DatInicioVigencia` e `DatFimVigencia` ENEL SP)**. Máximos globais do dataset: início 2026-09-30, fim 2027-09-29. 628 linhas ENEL SP cobrem 2026-10-19. 103 agentes têm B1/Residencial/Convencional cobrindo 2026-10-19 (de 115 CNPJs). As primeiras linhas do arquivo são de 2010: ordenação não é cronológica, nunca confiar no início do arquivo. Fim de vigência é inclusivo na prática (um fim em 07-03 é seguido por um início em 07-04).
- **Linhas reais filtradas, ENEL SP, vigência 2026-07-04→2027-07-03, B1 + Convencional + Classe Residencial + SubClasse Residencial + Detalhe "Não se aplica" + Posto "Não se aplica" + Unidade MWh + Acessante "Não se aplica"** (log `probes/probe4.log`):

```
DscREH;SigAgente;NumCNPJDistribuidora;DatInicioVigencia;DatFimVigencia;DscBaseTarifaria;DscSubGrupo;DscModalidadeTarifaria;DscClasse;DscSubClasse;DscDetalhe;NomPostoTarifario;DscUnidadeTerciaria;SigAgenteAcessante;VlrTUSD;VlrTE
RESOLUÇÃO HOMOLOGATÓRIA Nº 3.596, DE 3 DE JULHO DE 2026;ELETROPAULO;61695227000193;2026-07-04;2027-07-03;Tarifa de Aplicação;B1;Convencional;Residencial;Residencial;Não se aplica;Não se aplica;MWh;Não se aplica;472,42;316,96   (aparece 2x idêntica)
RESOLUÇÃO HOMOLOGATÓRIA Nº 3.596, DE 3 DE JULHO DE 2026;ELETROPAULO;61695227000193;2026-07-04;2027-07-03;Base Econômica;B1;Convencional;Residencial;Residencial;Não se aplica;Não se aplica;MWh;Não se aplica;453,32;308,11   (aparece 2x idêntica)
```

  Soma Tarifa de Aplicação: 472,42 + 316,96 = 789,38 R$/MWh = 0,78938 R$/kWh (sem tributos/bandeiras). Soma Base Econômica: 453,32 + 308,11 = 761,43 R$/MWh. O dicionário (texto extraído em `probes/dd-tarifas-extracted.txt`, v1.0 de 15/3/2022) distingue claramente as bases: "Tarifa de Aplicação" é a tarifa usada pela distribuidora para o faturamento dos acessantes (valores da Resolução Homologatória) e "Base Econômica" é usada estritamente para cálculo tarifário. O plano usa "Tarifa de Aplicação": **verificado pelo dicionário**, não é mais hipótese.
- **Armadilhas reais encontradas**: (a) linhas exatas duplicadas (2×) → deduplicar linhas idênticas, nunca somar; (b) subclasses de benefício (Baixa Renda, Tarifa/Desconto Social) no mesmo B1/Convencional → exigir `DscSubClasse == "Residencial"`; (c) variante `SCEE` em `DscDetalhe` com TE diferente (37,36) → exigir "Não se aplica"; (d) `Convencional pré-pagamento` é outra modalidade; (e) registros `kW` (demanda) e `Branca` existem → excluir; (f) períodos partidos com a mesma REH.
- Dicionário PDF `dd-tarifas-por-distribuidora.pdf` baixado (198 697 B, sha256 `6233892f…bacabc6ef`). Meu probe inicial NÃO extraiu o texto (sem `pdftotext`/`pdftoppm`; WebFetch recebeu streams FlateDecode). Depois, o agente `sdd-plan-reviewer` extraiu o texto para `probes/dd-tarifas-extracted.txt` (versão 1.0 de 15/3/2022, nomes de campo do dicionário diferem do cabeçalho do CSV, ex.: `DscBaseTarifa`/`DscUnidade`). Esse texto diz que a **Tarifa de Aplicação é a tarifa usada pela distribuidora para faturar os acessantes** e a **Base Econômica é usada estritamente para cálculo tarifário**; a unidade é R$/kW ou R$/MWh para TUSD e R$/MWh para TE. Fica verificado por leitura do dicionário (extração feita por agente, não por mim): D5 deixa de ser mera hipótese. Continua NÃO verificado o significado exato de `SCEE` e se TUSD/TE de B1 trazem algo além do componente de energia.

## 2. ANEEL — IndQual Município (o que realmente contém)

- `package_show?id=indqual-municipio` → HTTP 200, 6499 B, sha256 `126dd107…c3a5f1`, fetched_at 2026-10-19T04:07:02Z, modified 2026-09-09. Dataset `db9c9f60-b3b5-4504-9dfe-2637922d53ce`, CSV `3f841488-80a8-42f2-a6ca-e0c593b228de` (2 182 847 B).
- CSV baixado: sha256 `4063c5ba8ddaaabf27dad1a115eaa5a3f509f6ed3d22ac5c25c20f0d21365e09`, fetched_at 2026-10-19T04:07:12Z, `Last-Modified` 2026-09-09. Codificação: NÃO é UTF-8 (falha); latin-1/cp1252 decodifica ("São Gonçalo dos Campos"). Separador `;`.
- **Header real (5 colunas): `DatGeracaoConjuntoDados;IdeConjUnidConsumidoras;CodMunicipio;NomMunicipio;SigUF`. NÃO possui distribuidora nem CNPJ nem datas de vigência.** É apenas município (código IBGE de 7 dígitos) ↔ conjunto de unidades consumidoras. 42 699 linhas, 5 574 municípios, 15 162 conjuntos. Portanto IndQual sozinho não identifica concessionária.
- Para obter a distribuidora: o conjunto é resolvido pelo dataset ANEEL "Indicadores Coletivos de Continuidade (DEC e FEC)" (dataset `d5f0712e-62f6-4736-8dff-9991f10758a7`), recurso CSV `fd69e1dd-fd66-4269-b60c-cc0b7eb221b4` (`indicadores-continuidade-coletivos-limite.csv`, 25 865 955 B, sha256 `6cf409fc39aed93553293209ad662c8462036362feafc6337ea9c414ee0d9e92`, fetched_at 2026-10-19T04:08:45Z, Last-Modified 2026-10-05) com header `DatGeracaoConjuntoDados;SigAgente;NumCNPJ;IdeConjUndConsumidoras;DscConjUndConsumidoras;SigIndicador;AnoLimiteQualidade;VlrLimite` (note a grafia diferente `IdeConjUndConsumidoras` vs `IdeConjUnidConsumidoras`). Log: `probes/probe7.log`, `probe6.log`.
- **Resultado do join (IndQual.conjunto → DEC/FEC.limite.agente)**: 5 574 municípios, 0 sem agente resolvido; distribuição de agentes por município: 1 agente = 4 701; 2 = 587; 3 = 232; 4 = 42; 5 = 9; 6 = 3. Só 6 conjuntos têm >1 CNPJ. Conclusão verificada: **múltiplas distribuidoras no mesmo município ocorrem em ~15% dos municípios** (ex.: 4315503 Restinga Seca: CELETRO, RGE SUL, UHENPAL; 3508405: CERIM, ELEKTRO).
- **Capital IBGE 3550308**: 201 conjuntos (contagem das linhas do log); 199 `ELETROPAULO`, 1 `CERIS`, 1 sem agente — quase todos `ELETROPAULO` (CNPJ 61695227000193); o conjunto 12486 mapeia para `CERIS` (CNPJ 57384943000182); o conjunto 12450 não aparece no arquivo de limites (sem agente). Logo, mesmo a capital é multi-distribuidora na fonte oficial. A relação é por conjunto elétrico, **sem proporção de unidades consumidoras por município**, sem vigência de concessão e sem ser cadastro de concessões: é indicador de qualidade.
- Limitações: dataset de indicadores, não cadastro de concessão; `DatGeracaoConjuntoDados` (2026-09-09 / 2026-10-05) são datas de geração, não de vigência de concessão. Dados geográficos de área de concessão (BDGD, `base-de-dados-geografica-da-distribuidora-bdgd`) existem no catálogo CKAN (package_search, fetched_at 2026-10-19T04:08:24Z) mas NÃO foram inspecionados (fora do tamanho de probe pequeno).

## 3. IBGE

- `https://servicodados.ibge.gov.br/api/v1/localidades/municipios/3550308` → HTTP 200, 171 B **gzip** (resposta veio comprimida apesar de não enviarmos `Accept-Encoding`: o cliente precisa tratar `Content-Encoding`/magic `1f8b`), sha256 `9de310fa…5eb72`. Corpo: `{"id":3550308,"nome":"São Paulo", … "UF":{"id":35,"sigla":"SP",…}}`. Confirma código 3550308 = São Paulo/SP. IBGE identifica o município, não a concessionária.

## 4. Enel — cidades atendidas

- `https://www.enel.com.br/pt-saopaulo/cidades-atendidas-pela-enel-distribuicao.html` → HTTP 200, 62 275 B, fetched_at 2026-10-19T04:09:06Z. O HTML estático não contém nomes de municípios (lista está numa imagem de mapa `mapa_concessao_SP.jpeg`/conteúdo dinâmico). Via WebFetch o texto afirma servir "24 municípios da região metropolitana do estado (incluindo a capital)". **Nomes dos 24 municípios: não verificados/inacessíveis.** Esta fonte é institucional, não dado estruturado.

## 5. Telemetria local Linux (log `probes/probe8.log`)

- CPU AMD Ryzen 7 1700, placa A320M-S2H, sem virtualização detectada, uid 1000.
- `/sys/class/powercap/` existe; zonas `intel-rapl:0` (name `package-0`, `enabled`=0) e `intel-rapl:0:0` (`core`), `max_energy_range_uj` = 65532610987 legível (0444); **`energy_uj` → PermissionError para usuário comum** (arquivo restrito a root). Não há `/sys/class/power_supply/*`, nem `hwmon power*_input`, nem `/dev/ipmi*`, nem `ipmitool`. Resultado: nenhuma energia de CPU nem de tomada medida nesta máquina sem privilégio; o produto deve reportar `unavailable(permission_denied)` e nunca zero. Não foi usado sudo nem alterado nenhum arquivo.
- Documentação primária do kernel (`docs.kernel.org/power/powercap/powercap.html`, fetched_at 2026-10-19T04:09:07Z, 21 975 B): árvore `intel-rapl:N[:M]` com `energy_uj`, `max_energy_range_uj`, `name`, `enabled`; zonas aninhadas (subzonas `core`, `uncore`/`dram`) — somar zona pai e filhas dupla-conta.

## 5b. Cabeçalhos HTTP do `limite.csv` (probe suplementar)

`HEAD` de `.../fd69e1dd-fd66-4269-b60c-cc0b7eb221b4/download/indicadores-continuidade-coletivos-limite.csv`, fetched_at 2026-10-19T04:20:57Z: HTTP 200, `Content-Type: text/csv`, `Content-Length: 25865955` (igual aos bytes baixados antes), `Last-Modified: Mon, 05 Oct 2026 05:20:57 GMT`, `ETag`, `Accept-Ranges: bytes`. (O `sha256` no JSON suplementar é o de corpo vazio, pois foi HEAD.) Logo a regra `text/csv` + `Content-Length` vale para os três CSVs; a suposição de aceitar `application/octet-stream`/`text/plain` deixa de ser necessária.

## 6. Windows Win32_PowerMeter

Campos listados na página Microsoft (lidos em `probes/ms_win32_powermeter.txt`): `Name`, `DeviceID`, `SupportCapabilities` (bitmask: SupportMeasurement 0, SupportThresholds 1, SupportBudgeting 2, SupportOnlyWhenDischarging 8), `MeterType` (0 = potência de entrada, 1 = saída), `SamplingPeriod` (ms), `BaseUnits` (uint16; "apenas watts" desde o Windows 7), `UnitModifier` (sint32; -3 ⇒ leitura × 0,001 da unidade base) e outros de averaging/budget. A página diz que a classe deriva de `CIM_NumericSensor` e que o medidor de sistema inteiro é associado à instância `Win32_ComputerSystem`. A propriedade de leitura NÃO está listada na página (herdada); sua verificação nas fontes Microsoft foi delegada ao diligence-followup.

- Doc primária Microsoft (`learn.microsoft.com/en-us/previous-versions/windows/desktop/powermeterprov/win32-powermeter`, fetched_at 2026-10-19T04:09:07Z, 46 042 B, "Last updated 2018-05-31"): classe do `PowerMeterProvider`, namespace `Root\CIMV2\power`, MOF `PowerMeterProvider.mof`, DLL `UmPoWmi.dll`, mínimo Windows 7 / Server 2008 R2. É página em "previous-versions" (documentação legada). Existência de hardware/provider real que exponha instâncias: **não verificada** (depende de um medidor suportado). **Nada foi testado em Windows.**

## 7. Resumo do que NÃO foi verificado (risco visível)

1. Dicionário ANEEL: "Tarifa de Aplicação × Base Econômica" foi lido (ver seção 1); permanece não verificado o significado de `SCEE` e se `VlrTUSD`/`VlrTE` de B1 já embutem algum componente além da energia.
2. Nomes dos 24 municípios da Enel (página só informa a contagem; nomes em imagem de mapa). O alias "Enel SP" ↔ `ELETROPAULO` / CNPJ `61695227000193` foi RESOLVIDO pela página oficial `golpes-e-fraudes.html` (seção 4).
3. Comportamento de `Win32_PowerMeter` em hardware real e disponibilidade em Windows 10/11 modernos.
4. RAPL com permissão (energy_uj) e comportamento em AMD Zen 1: não foi lido (permissão negada).
5. Estabilidade futura de URLs/resource IDs/schema da ANEEL e da codificação dos CSVs.
6. Cobertura geográfica fina (por endereço/CEP) dentro do município: não coberta por nenhuma fonte inspecionada.
7. Regras tributárias/bandeiras: não pesquisadas nesta fase (fora do escopo; modelo manual all-in).

## Índice de proveniência

| Item | Arquivo |
|---|---|
| package_show tarifas / indqual / IBGE | `probes/probe1.log`, `pkg_tarifas.json`, `pkg_indqual.json`, `ibge_3550308.json` |
| downloads CSV (hash, headers) | `probes/probe2.log` |
| schema/domínios | `probes/probe3.log` |
| ENEL SP, vigências, linhas filtradas | `probes/probe4.log` |
| busca CKAN, multiplicidade IndQual | `probes/probe5.log` |
| dataset DEC/FEC (recursos, headers) | `probes/probe6.log` |
| join conjunto→distribuidora | `probes/probe7.log` |
| telemetria Linux | `probes/probe8.log` |
| enel/kernel/microsoft (fetch HTML) | `probes/probe9.log`, `probe10.log`, `*.txt` |
| scripts | `scripts/probe1..10.py` |

(Caminho base: `diretório privado de planejamento (fora do repositório)/`.)
