# Plano: pc-energy-cost — custo em BRL da energia atribuível a um PC

Data do plano: 2026-10-19. Projeto novo e isolado em `.` (sem repositório git, sem código herdado, sem testes herdados). Pesquisa e proveniência: `requirements/research.md`. Requisitos originais: `requirements/spec.md`. Logs brutos dos probes e evidências dos agentes: `diretório privado de planejamento (fora do repositório)/` (fora do repositório).

## Contexto

Programa standalone, de código comum (sem agente, sem LLM, sem Hermes, sem nuvem de IA no runtime), que estima em BRL o custo da energia atribuível a um PC ligado por uma duração planejada ou medida. O resultado é uma **estimativa da energia atribuível**, não uma fatura residencial completa. A tarifa é obtida automaticamente do dado aberto oficial da ANEEL; o município é ligado à distribuidora por fonte oficial; a telemetria é opcional e honesta sobre o escopo (tomada vs CPU).

Os probes desta fase (ver `requirements/research.md`) mudaram o desenho em quatro pontos: (1) o dataset de tarifas nomeia a distribuidora da capital como `ELETROPAULO` (CNPJ `61695227000193`), não "ENEL SP"; (2) o IndQual Município NÃO tem distribuidora, só município↔conjunto, e precisa de um join com o dataset DEC/FEC; (3) até a capital tem mais de uma distribuidora na fonte oficial (ELETROPAULO e CERIS); (4) o CSV de tarifas tem linhas duplicadas e variantes de benefício que levariam a erro se somadas.

## Abordagem

Python 3.11+, stdlib sempre que sensato, CLI como primeira UI utilizável (texto em português + JSON versionado), SQLite para preferências/mapeamentos/cache indexado. DDD leve: quatro contextos com domínio puro (sem HTTP, SQLite, SO ou UI), casos de uso em `application`, adaptadores em `infrastructure`, composição única em `composition.py`. Sem framework DDD; sem classes onde uma função basta.

### Defaults PROVISÓRIOS (precisam de aprovação humana junto com este plano)

| ID | Default | Observação |
|---|---|---|
| D1 | Python ≥ 3.11, stdlib; única dependência de runtime: `tzdata; sys_platform == "win32"` (condicional ao Windows, porque o Windows não traz base IANA e `ZoneInfo("America/Sao_Paulo")` falharia; fonte: docs.python.org zoneinfo, ver Due diligence record); `pytest` e `build` só em dev | Windows WMI via `powershell.exe` somente leitura (sem pywin32). Default PROVISÓRIO para aprovação humana: não foi aprovado. Descartado: offset fixo UTC-3, historicamente incorreto (o Brasil teve horário de verão até 2019). Sem `tzdata` e sem base do sistema ⇒ erro `timezone_data_missing` (exit 2), nunca fuso silencioso |
| D2 | CLI `pc-energy-cost` (`python -m pc_energy_cost`) com saída humana pt-BR e `--json` (schema versionado `schema_version: "1"`) | |
| D3 | "São Paulo" = capital, IBGE `3550308`; o catálogo inicial é PARCIAL: só municípios cujo mapeamento foi construído a partir das fontes oficiais lidas, sem prometer catálogo nacional | |
| D4 | Perfil tarifário inicial: B1 residencial convencional, subclasse "Residencial", sem tarifa social/branca/pré-pagamento/SCEE | |
| D5 | Base tarifária: `Tarifa de Aplicação`. O texto extraído do dicionário (`probes/dd-tarifas-extracted.txt`, v1.0 de 15/3/2022) diz: "A Tarifa de Aplicação é a tarifa utilizada pela distribuidora para o faturamento dos acessantes [...] Já a Tarifa Base Econômica refere-se aos valores que serão utilizados estritamente para cálculo tarifário" | `Base Econômica` só via flag explícita. Os nomes de campo do dicionário (`DscResolucaoHomologatoria`, `DscBaseTarifa`, `DscUnidade`, `VlrTusd`, `VlrTe`) diferem do cabeçalho real do CSV; o schema guard usa os nomes do CSV |
| D6 | Arredondamento: `ROUND_HALF_UP`, 2 casas apenas na apresentação e no total; cálculo interno em `Decimal` com contexto de 28 dígitos; sem `float` em dinheiro. Energia na apresentação: kWh com 3 casas, `ROUND_HALF_UP` (como em A1 `1,000 kWh`); o JSON traz também o valor interno sem arredondar | |
| D7 | TTL de refresh 24h; offline "stale" só com `--permitir-cache-vencido`, sempre exibindo idade e vigência | |
| D8 | Município com mais de uma distribuidora ⇒ resultado `ambiguous`; exige `--distribuidora <CNPJ>` ou escolha interativa em TTY (nunca pergunta com `--json` ou stdin/stdout não-TTY: devolve erro `supplier_ambiguous` com os candidatos); a escolha do usuário é persistida separada da fonte oficial. Não há "predominante" automático | Para a capital: ELETROPAULO 199 conjuntos, CERIS 1, 1 sem agente |
| D9 | Fuso `America/Sao_Paulo` via `zoneinfo`; intervalos `[início, fim)`; vigências ANEEL tratadas como `[início, fim]` por datas inclusivas (confirmado pela adjacência 07-03/07-04) | |
| D10 | Data futura fora de vigência: erro `tariff_not_in_effect`; projeção só com `--projetar-ultima-tarifa` (warning explícito) ou `--tarifa-manual-total` | |
| D11 | Tributos/bandeiras: não modelados automaticamente; modelo tributário por fórmula ADIADO. Tarifa manual única: `--tarifa-manual-total <R$/kWh>` (all-in, derivada da fatura) com `--inclui` (lista de `tributos`, `bandeira`, `encargos`, ou `nao-declarado`, o default). Adicional opcional: `--adicional-kwh <R$/kWh>` exige `--adicional-tipo` (`bandeira`, `tributos`, `outro`). Política verificável de dupla inclusão na seção "Tarifa manual e adicionais" | Provisório |
| D14 | Limites numéricos de entrada (PROVISÓRIOS, ajustáveis só por mudança de plano): potência 0 ≤ W ≤ 100 000 com até 3 casas decimais; duração 0 ≤ h ≤ 87 600 (10 anos) com até 4 casas; tarifa e adicional 0 ≤ R$/kWh ≤ 100 com até 6 casas; `--max-gap` entre 1 s e 24 h; texto numérico ≤ 32 caracteres; CSV de medição ≤ 1 000 000 linhas. Fora do limite ou com mais casas do que o permitido ⇒ `invalid_input` (nunca arredondamento silencioso de entrada) | Provisório |
| D15 | Escopo de medição vindo do Windows WMI no v1: NUNCA `whole_system_ac`. No v1, como a associação medidor↔`Win32_ComputerSystem` não é comprovável (nenhuma classe de associação publicada), toda instância WMI sai como `component`; `whole_system_unverified` (sistema inteiro, domínio AC/DC não comprovável) fica reservado para quando um plano revisado nomear a classe de associação verificada ou houver hardware Windows validado; dúvida em qualquer condição ⇒ `Unavailable` ou `component` explícito | Provisório; sem hardware Windows validado |
| D12 | Cenário de nameplate (PSU) só como `--cenario-potencia-nominal W`, rotulado `scenario`, nunca como telemetria | |
| D13 | Códigos de saída da CLI: 0 sucesso; 2 entrada inválida (`invalid_input`, `ambiguous_decimal`, `invalid_interval`, `overlapping_intervals`, `timezone_data_missing`, `double_inclusion`, `inclusion_undeclared`, `insufficient_coverage` de série CSV, erros de CSV de medição); 3 ambiguidade/sem cobertura (`supplier_ambiguous`, `unsupported`, `tariff_ambiguous`); 4 tarifa/dados (`tariff_not_found`, `tariff_not_in_effect`, `schema_mismatch`, `unexpected_html`, `download_incomplete`, `cache_corrupted`); 5 rede (`network_unavailable`); 6 telemetria indisponível (`Unavailable(...)`, inclusive `insufficient_coverage` de contador RAPL) | Provisório; os testes CLI fixam esta tabela |

### Fora de escopo (v1)

Plugin/adaptador Proxmox (apenas a porta documentada em `docs/extensoes.md`), tarifa branca/social, tributos por fórmula, rateio de custos fixos, geolocalização por CEP/endereço, GUI, publicação/PyPI/GitHub remoto, qualquer serviço ou driver privilegiado, qualquer uso de sudo.

## Linguagem ubíqua e contextos (DDD leve)

- **EnergyEstimation**: `Watts`, `Wh`, `KWh`, `Duration`, `UnitRateBRLPerKWh`, `MoneyBRL` (value objects `Decimal`); `PowerProfile` (potência média ou série temporal); `Schedule` (intervalos `[início, fim)` sem sobreposição, em `America/Sao_Paulo`); `CostEstimate` (energia, tarifa usada, custo, avisos, escopo de medição). Regra: `kWh = W × horas / 1000`; zero é válido; negativo/NaN/∞ e valores acima dos limites numéricos de D14 são inválidos. `CostEstimate` inclui `requested_duration`, `coverage_duration`, `excluded_duration` e `partial_data` (ver "Cobertura de medição").
- **TariffCatalog**: `Distributor(cnpj, sig_agente, aliases verificados)` (para o CNPJ `61695227000193`: `sig_agente` `ELETROPAULO`, alias verificado `Eletropaulo Eletricidade de São Paulo S.A`, texto da página oficial da Enel `golpes-e-fraudes.html` junto ao CNPJ; o rótulo de exibição "Enel São Paulo" é só uma inferência da página (rótulo de navegação), não alias de busca; nenhum outro alias é aceito sem fonte), `TariffProfile`, `TariffRecord` (TUSD e TE em R$/MWh, vigência, base, REH), `ResolvedTariff` (R$/kWh + `Provenance`), `TariffSource` (porta). Regra: TE+TUSD (ambas R$/MWh) somadas e divididas por 1000; nunca somar kW, nunca somar duplicatas ou períodos.
- **LocationSupplierMapping**: `Municipality(ibge_code, name, uf)`, `SupplierLink(municipality, distributor, source, evidence, confidence, user_confirmed)`; relação muitos-para-muitos; resultado `Resolved | Ambiguous(candidates) | Unsupported`.
- **Metering**: porta `MeteringProvider` com `availability()` ⇒ `Available(scope)` ou `Unavailable(reason)`, `scope ∈ {whole_system_ac, whole_system_unverified, cpu_package, component, manual, scenario}`, `read()` ⇒ amostras `(timestamp, quantidade, unidade)` distinguindo potência (W) de energia acumulada (µJ/Wh).

Regra de dependência (testada por `tests/architecture/test_layering.py`): `domain` não importa nada fora de `domain` e da stdlib pura (sem `sqlite3`, `urllib`, `os`, `subprocess`, `csv`); `application` importa só `domain`; `infrastructure` e `interface` importam `application`/`domain`; só `composition.py` importa tudo.

## Arquivos a criar (caminhos exatos futuros)

Raiz do projeto: `./`.

```
pyproject.toml
README.md                                   # pt-BR: instalação, uso, limites, exemplos
docs/arquitetura.md
docs/fontes-de-dados.md                     # proveniência, hashes, schemas reais
docs/telemetria.md                          # escopos, RAPL, WMI, limites
docs/extensoes.md                           # porta Proxmox (somente documentação)
docs/checklist-instalacao.md
docs/matriz-requisitos-testes.md
src/pc_energy_cost/__init__.py              # __version__
src/pc_energy_cost/__main__.py
src/pc_energy_cost/composition.py
src/pc_energy_cost/domain/shared/errors.py          # hierarquia DomainError + códigos estáveis
src/pc_energy_cost/domain/shared/units.py           # Watts, Wh, KWh, Duration, UnitRate
src/pc_energy_cost/domain/shared/money.py           # MoneyBRL, regra de arredondamento
src/pc_energy_cost/domain/shared/parsing.py         # decimal pt-BR/JSON, limites de entrada
src/pc_energy_cost/domain/energy_estimation/schedule.py     # Interval, Schedule, overlap
src/pc_energy_cost/domain/energy_estimation/integration.py  # trapézio/degraus, gaps, duplicatas
src/pc_energy_cost/domain/energy_estimation/estimate.py     # CostEstimate, divisão por vigências
src/pc_energy_cost/domain/tariff_catalog/model.py
src/pc_energy_cost/domain/tariff_catalog/selection.py       # filtros do perfil, dedupe, ambiguidade
src/pc_energy_cost/domain/location_supplier/model.py
src/pc_energy_cost/domain/location_supplier/resolver.py
src/pc_energy_cost/domain/metering/model.py                 # amostras, escopos, Unavailable
src/pc_energy_cost/domain/metering/ports.py                 # MeteringProvider (Protocol)
src/pc_energy_cost/application/ports.py                     # TariffSource, SupplierSource, Clock, Store
src/pc_energy_cost/application/estimate_cost.py
src/pc_energy_cost/application/resolve_tariff.py
src/pc_energy_cost/application/resolve_supplier.py
src/pc_energy_cost/application/measure_power.py
src/pc_energy_cost/application/refresh_catalog.py
src/pc_energy_cost/infrastructure/http/fetcher.py           # timeout, limite de bytes, gzip, content-type
src/pc_energy_cost/infrastructure/aneel/ckan.py             # package_show, escolha do resource por id/formato
src/pc_energy_cost/infrastructure/aneel/tariff_csv.py       # parser streaming, schema guard
src/pc_energy_cost/infrastructure/aneel/supplier_csv.py     # IndQual + DEC/FEC limite → vínculos
src/pc_energy_cost/infrastructure/cache/file_cache.py       # escrita atômica, hash, TTL, quarentena
src/pc_energy_cost/infrastructure/persistence/sqlite_store.py   # preferências, vínculos, índice do cache, migrações
src/pc_energy_cost/infrastructure/metering/manual.py
src/pc_energy_cost/infrastructure/metering/csv_series.py
src/pc_energy_cost/infrastructure/metering/linux_rapl.py
src/pc_energy_cost/infrastructure/metering/windows_wmi.py   # PowerShell somente leitura
src/pc_energy_cost/interface/cli/main.py                    # argparse, códigos de saída
src/pc_energy_cost/interface/cli/render_pt.py
src/pc_energy_cost/interface/cli/json_schema.py             # schema v1 + validador mínimo
tests/unit/test_units_money.py
tests/unit/test_parsing.py
tests/unit/test_schedule.py
tests/unit/test_integration.py
tests/unit/test_estimate.py
tests/unit/test_tariff_selection.py
tests/unit/test_supplier_resolver.py
tests/application/test_estimate_cost.py
tests/application/test_refresh_catalog.py
tests/application/test_resolve_supplier.py
tests/application/test_measure_power.py
tests/infrastructure/test_fetcher_cache.py
tests/infrastructure/test_ckan.py
tests/infrastructure/test_tariff_csv.py
tests/infrastructure/test_supplier_csv.py
tests/infrastructure/test_sqlite_store.py
tests/infrastructure/test_metering_manual_csv.py
tests/infrastructure/test_metering_rapl.py
tests/infrastructure/test_metering_wmi.py
tests/install/test_install.py       # marcador `install`; sdist → wheel → venv limpo
tests/contract/test_metering_provider_contract.py
tests/contract/test_tariff_source_contract.py
tests/architecture/test_layering.py
tests/cli/test_cli_end_to_end.py
tests/live/test_live_aneel.py       # marcador `live`, rede real, fora do CI padrão
tests/live/test_live_linux_rapl.py  # marcador `live`; skip explícito se sem permissão
tests/live/test_live_windows_wmi.py # marcador `live_windows`; só roda em Windows com hardware
tests/fixtures/aneel/tarifas_eletropaulo.csv      # recorte REAL: 17 colunas + linhas ELETROPAULO (duplicatas, Baixa Renda, SCEE, Base Econômica, kW)
tests/fixtures/aneel/indqual_capital.csv          # recorte REAL, latin-1, 5 colunas
tests/fixtures/aneel/limite_recorte.csv           # recorte REAL, UTF-8, 8 colunas (inclui conjunto 6818 e 12450)
tests/fixtures/aneel/package_show_tarifas.json    # resposta REAL do CKAN
tests/fixtures/aneel/package_show_indqual.json
tests/fixtures/aneel/package_show_decfec.json
tests/fixtures/metering/serie_valida.csv
tests/fixtures/metering/serie_gap.csv
tests/fixtures/metering/serie_invalida.csv
tests/fixtures/metering/powercap_fake/            # árvore sintética de sysfs (rotulada fake)
```

(Cada passo da seção `## Implementation steps` lista caminhos relativos completos, sem `...`; os blocos acima são a fonte.)

## O que permanece inalterado

`.claude/settings.local.json` (protege atribuição), `.gitignore`, `requirements/spec.md`. Nada de `git init` ou commit sem nova aprovação. Esta fase não cria código de produto.

## Tarifa automática ANEEL (especificação)

Fonte: CKAN `https://dadosabertos.aneel.gov.br/api/3/action/package_show?id=tarifas-distribuidoras-energia-eletrica`; recurso CSV identificado por `id` `fcf2906c-7c32-4b9b-a637-054e7a5234f4` (fallback: único recurso `format == CSV` e nome contendo `tarifas-homologadas`; se ambíguo ⇒ erro). Download limitado (cap 300 MB, timeout de conexão 30 s / total 300 s), escrita em arquivo `.part` + `os.replace`, hash SHA-256, `Content-Type` deve ser `text/csv` (HTML ⇒ `unexpected_html`).

Truncamento: bytes recebidos ≠ `Content-Length` (o probe recebeu `Content-Length: 178230008`) ou conexão encerrada antes do fim ⇒ `download_incomplete`. Não há hash publicado pela ANEEL; o SHA-256 é calculado localmente e serve para proveniência e para detectar corrupção do cache (índice ≠ arquivo ⇒ `cache_corrupted`).

Schema guard: o cabeçalho tem que conter exatamente as 17 colunas observadas; faltando/renomeada ⇒ `schema_mismatch`. Codificação `utf-8-sig` (o arquivo baixado em 2026-10-19 NÃO tem BOM, começa com `"Da`; `utf-8-sig` aceita os dois casos); separador `;`, campos entre aspas; decimal pt-BR parseado com `Decimal` (aceita `,00`). Dedupe só de linhas totalmente idênticas.

Indexação: `atualizar-catalogo` faz o parse streaming UMA vez por download e grava as linhas normalizadas (todas as colunas, valores como texto `Decimal`, hash do arquivo de origem) em tabela SQLite indexada por `(NumCNPJDistribuidora, DatInicioVigencia, DatFimVigencia)`; `estimar` consulta o SQLite, nunca re-parseia os 178 MB por consulta.

Filtro do perfil D4, sobre as colunas reais: `NumCNPJDistribuidora == cnpj`, `DscSubGrupo == "B1"`, `DscModalidadeTarifaria == "Convencional"`, `DscClasse == "Residencial"`, `DscSubClasse == "Residencial"`, `DscDetalhe == "Não se aplica"`, `NomPostoTarifario == "Não se aplica"`, `DscBaseTarifaria == "Tarifa de Aplicação"`, `DscUnidadeTerciaria == "MWh"`, `SigAgenteAcessante == "Não se aplica"`, e `DatInicioVigencia <= data <= DatFimVigencia`. Após dedupe, exatamente 1 registro deve restar; 0 ⇒ `tariff_not_found` (o perfil não existe para o CNPJ em nenhuma vigência) ou `tariff_not_in_effect` (o perfil existe, mas nenhuma vigência cobre a data); >1 distintos ⇒ `tariff_ambiguous` (nunca escolher). Resultado = (TUSD + TE) / 1000 em R$/kWh, com proveniência completa: URL, resource id, `metadata_modified`, `Last-Modified`, `DatGeracaoConjuntoDados`, `fetched_at` UTC, SHA-256, REH, vigência, unidades originais, critérios aplicados e o aviso fixo "sem tributos, bandeiras e encargos fixos".

Dataset desatualizado: se a data pedida for posterior à maior `DatFimVigencia` do agente ⇒ `tariff_not_in_effect` (D10); jamais apresentar como "tarifa de hoje". Valor de referência dos probes (apenas para a matriz de aceitação, os fixtures são cópias reais): ELETROPAULO, vigência 2026-07-04→2027-07-03, TUSD 472,42 + TE 316,96 = 789,38 R$/MWh = 0,78938 R$/kWh. Vigência anterior (re-verificada no CSV na revisão do plano): 2026-01-01→2026-07-03, REH 3.477/2025, TUSD 432,44 + TE 292,74 = 725,18 R$/MWh = 0,72518 R$/kWh; e 2025-07-04→2025-12-31 com a MESMA REH e os MESMOS valores (período partido): são dois registros distintos por vigência, nunca somados.

## Mapeamento município ↔ distribuidora (especificação)

Fontes: IndQual Município (CKAN `package_show?id=indqual-municipio`, recurso CSV `3f841488-80a8-42f2-a6ca-e0c593b228de`; `CodMunicipio` ↔ `IdeConjUnidConsumidoras`, latin-1/cp1252, 5 colunas) e DEC/FEC `indicadores-continuidade-coletivos-limite.csv` (dataset `d5f0712e-62f6-4736-8dff-9991f10758a7`, recurso `fd69e1dd-fd66-4269-b60c-cc0b7eb221b4`; `IdeConjUndConsumidoras` ↔ `SigAgente`/`NumCNPJ`, 8 colunas). Mesmas regras de download/cache/schema guard da tarifa (cabeçalhos exatos de `requirements/research.md` §2), com codificação por arquivo. O `Content-Type` do `limite.csv` foi observado em `HEAD` (2026-10-19T04:20:57Z, `probes/supplement-probe.json`): `text/csv`, `Content-Length: 25865955`. Portanto o fetcher exige `text/csv` para os TRÊS CSVs; qualquer outro tipo (ex.: HTML) ⇒ `unexpected_html`, sem lista alternativa por recurso. (Observado por HEAD em 2026-10-19T04:20:57Z e por GET em 2026-10-19T04:33:15Z, `probes/supplement-probe-get-limite.json`: `text/csv`, `Content-Length` 25865955; ambos por `urllib` do orquestrador, não por WebFetch.)

Detalhes verificados na revisão do plano (re-execução sobre os arquivos de `probes/`): (a) `limite.csv` é UTF-8 (decodifica em `utf-8-sig`), NÃO latin-1 como o IndQual; (b) `SigAgente` vem com espaços à direita (`"ELETROPAULO         "`) ⇒ aplicar `strip()` em todos os campos texto; a chave do vínculo é `NumCNPJ`, a sigla é só rótulo; (c) os 6 conjuntos com >1 CNPJ (ex.: 6818–6823) são SUCESSÕES históricas (`EBO` em `AnoLimiteQualidade` 2000–2010, `EPB` 2010–2013), não coexistência; por isso, para cada conjunto usa-se só o(s) agente(s) do MAIOR `AnoLimiteQualidade` daquele conjunto (empate de CNPJs no mesmo ano ⇒ ambos candidatos), e o ano usado vai para `evidence`. O join por conjunto produz `SupplierLink(source="aneel:indqual+dec-fec", confidence="official_indicator_join", evidence={n_conjuntos, conjuntos_sem_agente, ano_limite_usado})`. A confiança é de indicador de qualidade, não de cadastro de concessão. `user_confirmed` é um vínculo separado (`source="user"`), nunca mescla com o oficial. Município sem conjunto resolvido ⇒ `Unsupported`. Município com ≥2 agentes ⇒ `Ambiguous` com candidatos e contagem de conjuntos. O catálogo inicial persistido é construído sob demanda (comando `atualizar-catalogo`) a partir dessas duas fontes e rotulado "parcial / indicativo".

IBGE: usado como identificador (código de 7 dígitos). A API do IBGE não faz parte do runtime v1 (os nomes vêm do IndQual); eventual cliente exige tratar resposta gzip mesmo sem `Accept-Encoding` (observado no probe).

## Telemetria (especificação)

- `ManualAverageWatts` e `CsvPowerSeries` (colunas exatas `timestamp,watts`; ISO-8601 com offset ou naive interpretado em `America/Sao_Paulo`): executáveis em qualquer plataforma. Integração por degraus (cada amostra vale até a próxima) é o padrão; trapézio opt-in. Duplicatas de timestamp idênticas com mesmo valor ⇒ uma; mesmo timestamp com valores diferentes ⇒ `csv_conflicting_duplicate`; timestamps fora de ordem ⇒ ordenados com aviso; linhas inválidas ⇒ erro com número da linha. Limites de D14 valem para cada linha. Regras de cobertura na próxima subseção.
- `LinuxRaplProvider` (energia CPU/package, SEMPRE parcial em relação ao PC; escopo `cpu_package`, nunca `whole_system_ac`; probe local: `energy_uj` negado para uid 1000 e `enabled`=0 em `package-0`):
  - **Zonas somadas**: somente zonas de topo cujo arquivo `name` seja exatamente `package-<N>` (regex `^package-[0-9]+$`) e cujo diretório seja `intel-rapl:<N>` sem segundo `:`. Qualquer outra zona de topo (ex.: `psys`, `dram`) e todas as subzonas (`intel-rapl:<N>:<M>`: `core`, `uncore`, `dram`) são listadas como `component` e NUNCA somadas ao package (`psys` pode sobrepor o package; a doc do kernel não cobre `psys`: ver Due diligence record).
  - **Indisponibilidade (nunca zero)**: `energy_uj` ou `max_energy_range_uj` ilegível/`PermissionError` ⇒ `Unavailable(permission_denied)`; `enabled` = `0` ⇒ `Unavailable(zone_disabled)` (política conservadora provisória: o plano não verificou se `enabled` governa a leitura de energia ou só o power capping); ausência de `/sys/class/powercap` ou de zona `package-N` ⇒ `Unavailable(no_rapl_zone)`; valor não numérico ou `max_energy_range_uj` ≤ 0 ⇒ `Unavailable(invalid_counter)`. Sem sudo, sem alterar permissões.
  - **Política de amostragem, wrap e reset (conservadora, limites provisórios)**: leitura em pares (anterior, atual) com relógio monotônico (`time.monotonic_ns()`) e relógio de parede lidos juntos. Constante `P_MAX_W = 1000` W por package (parâmetro `--rapl-max-watts`, 1 ≤ valor ≤ 10 000). Intervalo máximo aceito `dt_max = max_energy_range_uj / (2 × P_MAX_W × 1 000 000)` segundos (metade do tempo mínimo de um wrap), limitado a 60 s e com piso de 0,5 s; a CLI amostra a cada `min(dt_max, 5 s)`. Para cada par (`dt` = diferença do relógio monotônico, salvo onde dito "de parede"): (1) `dt > dt_max` ⇒ intervalo excluído com razão `indeterminate_wrap` (múltiplos wraps não são distinguíveis); (2) se a diferença entre `dt` monotônico e `dt` de parede for > 2 s (suspensão/salto de relógio) ⇒ excluído `clock_discontinuity`; (3) `atual ≥ anterior` ⇒ `delta = atual − anterior`; (4) `atual < anterior` ⇒ assume UM wrap: `delta = atual + max_energy_range_uj − anterior`; (5) potência média do par = `delta / dt`; se > `P_MAX_W` ⇒ excluído `counter_reset_or_invalid` (um reset do contador é indistinguível de wrap, e o teste de plausibilidade é a única defesa); (6) intervalos excluídos entram em `excluded_duration` e `partial_data = true`; todos excluídos ⇒ `insufficient_coverage`. Nada disso foi medido: o plano só especifica e os testes (matriz) simulam contadores fake.
- `WindowsWmiProvider` (não é implementado na fase de planejamento; na implementação é criado em `windows_wmi.py` e testado só com fakes; sem hardware Windows validado): `powershell.exe -NoProfile -NonInteractive -Command` com `Get-CimInstance -Namespace root/CIMV2/power -ClassName Win32_PowerMeter` (somente leitura, timeout 10 s, argumentos fixos, sem interpolação de entrada do usuário). A mera existência de instância NÃO autoriza `whole_system_ac` (D15). Para devolver `Available` o provider exige, TODAS: (a) leitura atual presente e numérica: a propriedade é `CurrentReading` (`sint32`), definida em `CIM_NumericSensor` (fonte Microsoft lida pelo diligence-followup) e herdada por `Win32_PowerMeter`, mas a página de `Win32_PowerMeter` NÃO a lista; por isso ela é tratada como documentada por herança e NÃO validada em hardware: valor ausente, nulo ou não numérico ⇒ `Unavailable(reading_property_unverified)`; (b) `UnitModifier` (`sint32`; -3 ⇒ ×0,001, confirmado na fonte Microsoft) presente, aplicando `leitura × 10^UnitModifier` em `Decimal`, e `BaseUnits` presente: a Microsoft diz que desde o Windows 7 só há watts, mas NÃO publica o código numérico, então o provider guarda o código bruto em `base_units_code` com o aviso `base_units_not_decoded` e não o decodifica; `BaseUnits` ou `UnitModifier` ausente ⇒ `Unavailable(unit_unknown)`; (c) `MeterType == 0` (entrada); `1` ou ausente ⇒ `component` explícito rotulado "potência de saída"/desconhecida, não sistema; (d) associação comprovada do medidor à instância `Win32_ComputerSystem`: nenhuma fonte Microsoft lida nomeia a classe de associação (só diz que o medidor de sistema inteiro "is associated with" essa instância; o perfil DMTF DSP1015 não foi verificado), então NO v1 a associação não é comprovável e TODA instância WMI sai como `component`; o escopo `whole_system_unverified` fica reservado e só se ativa por mudança de plano que nomeie uma classe de associação verificada ou por validação em hardware Windows; (e) `SupportOnlyWhenDischarging` não sinalizado: a Microsoft chama `SupportCapabilities` de bitmask mas lista os "valores" 0, 1, 2 e 8, então a codificação é ambígua; política conservadora: considera-se sinalizado se `(caps & 0x8) != 0` OU `(caps & 0x100) != 0` ⇒ `Unavailable(only_when_discharging)` (esse medidor só reporta em descarga de bateria/UPS); `SupportMeasurement` (listado como 0) NÃO é testado como flag, e o suporte a medição é provado apenas por uma leitura válida; (f) `Status` (string herdada de `CIM_ManagedSystemElement`, ex.: "OK") igual a "OK" quando exposto (ausente é aceito com aviso `status_not_exposed`, pois a página da classe não o lista), e leitura não negativa e ≤ 100 000 W; falha ⇒ `Unavailable(invalid_reading)`; (g) o intervalo de amostragem (`SamplingPeriod`, em milissegundos) respeitado, sem tratar leitura repetida dentro do período como amostras novas. `MeterType == 0` ("input power") e a associação ao `Win32_ComputerSystem` NÃO provam (nenhuma fonte Microsoft lida dá significado AC/DC à potência de entrada, confirmado pelo diligence-followup) que o domínio medido é tomada AC (pode ser entrada DC da fonte): onde não comprovável, nunca rotular como tomada. O provider NUNCA grava propriedades graváveis (`ConfiguredBudget`, `BudgetEnabled`, `AveragingInterval`). Classe/namespace ausente ou zero instâncias ⇒ `Unavailable(no_power_meter_provider)`; nunca zero fabricado nem escala de CPU para PC inteiro. **Nunca testado em Windows.**

### Cobertura de medição (série CSV, RAPL e qualquer fonte temporal)

Janela solicitada = `--inicio/--fim` (ou do primeiro ao último timestamp da série). Entre duas amostras consecutivas a diferença `Δ ≤ --max-gap` (default 5 min, faixa 1 s–24 h por D14) é CONSIDERADA COBERTA e usa o valor da amostra anterior (degraus); `Δ > --max-gap` é EXCLUÍDA, sem interpolar. Amostras fora da janela são recortadas a ela. Com `--inicio` anterior à primeira amostra, `[início, primeira)` é EXCLUÍDO (razão `no_sample`; nada se estende para trás). A última amostra cobre `[último, fim)` somente se `fim − último ≤ --max-gap`; caso contrário `[último, fim)` é EXCLUÍDO (razão `gap`). Toda estimativa a partir de série ou contador reporta `requested_duration`, `coverage_duration`, `excluded_duration` (lista de intervalos excluídos com razão) e `partial_data` (true se `excluded_duration > 0`). O custo cobre SÓ a energia da parte coberta, sem extrapolar para a janela inteira, e a saída traz o aviso `partial_data`. Se `coverage_duration == 0` ⇒ erro `insufficient_coverage` (exit 2 para CSV; exit 6 para contador), nunca "0 kWh / R$ 0,00 para a duração inteira". Zero físico é distinto: potência média manual 0 W (ou série com `watts = 0` COBERTA) é válido e custa R$ 0,00. Séries com amostras espaçadas mais do que o default exigem `--max-gap` explícito (ex.: amostras de hora em hora exigem `--max-gap 1h` ou maior).

### Tarifa manual e adicionais (D11, D14)

Unidade de todos os preços: R$/kWh, `Decimal`, 0 ≤ valor ≤ 100, até 6 casas decimais (D14). Negativo ⇒ `invalid_input` (descontos/créditos não são modelados). Zero é válido (custo R$ 0,00) com aviso `zero_rate`. `--tarifa-manual-total` é all-in derivado da fatura; `--inclui` declara o que ela já contém (`tributos`, `bandeira`, `encargos`; default `nao-declarado`); a saída (texto e JSON) lista `inclusoes_declaradas` e a composição `tarifa_base`, `adicional`, `taxa_total`. Regras: (1) `--adicional-kwh` exige `--adicional-tipo ∈ {bandeira, tributos, outro}`; (2) com `--tarifa-manual-total`, se o tipo do adicional (`bandeira` ou `tributos`) já consta em `--inclui` ⇒ erro `double_inclusion` (exit 2); (3) com `--tarifa-manual-total` e `--inclui nao-declarado`, qualquer `--adicional-kwh` ⇒ erro `inclusion_undeclared`, porque não dá para provar que não duplica; tipo `outro` só passa se `--inclui` for explícito; (4) com tarifa ANEEL automática (que exclui tributos e bandeiras), o adicional é permitido e somado, e a saída diz que a tarifa base não inclui tributos/bandeiras; (5) encargos fixos da residência nunca são rateados ao PC; (6) o domínio soma `taxa_total = tarifa_base + adicional` em `Decimal` e arredonda só o custo final; (7) `--adicional-tipo` sem `--adicional-kwh`, ou `nao-declarado` combinado com outro valor de `--inclui` ⇒ `invalid_input`. Valores negativos na CLI: o `argparse` só reconhece `-1`/`-0.1` como número; `-0,10` seria lido como opção, por isso os testes usam a forma `--opcao=-0,10` e a CLI deve converter erros de uso do `argparse` em `invalid_input` (exit 2, com `error.code` em `--json`).
- Wallplug/IPMI/smartplug: apenas documentados como possíveis providers futuros (`docs/extensoes.md`); Proxmox apenas porta documentada. PSU rating nunca vira watts medidos (D12).

## Casos de borda

| Caso | Comportamento esperado |
|---|---|
| Duração 0 ou potência 0 | custo `R$ 0,00`, sem aviso de erro |
| Potência/duração negativa, NaN, inf, notação científica, acima dos limites de D14 (ex.: 100 000,001 W; 87 600,0001 h; 4 casas em W) | `invalid_input` (código estável), exit 2; exatamente 100 000 W e 87 600 h são aceitos |
| Série com todos os intervalos > `--max-gap` | `insufficient_coverage`, não R$ 0,00 |
| Série parcialmente coberta | custo só da parte coberta, `partial_data: true`, `coverage_duration`/`excluded_duration` preenchidos |
| `--tarifa-manual-total` + `--adicional-kwh` de tipo já declarado em `--inclui` / sem `--inclui` explícito | `double_inclusion` / `inclusion_undeclared` (ver "Tarifa manual e adicionais") |
| Windows sem `tzdata` e sem base IANA | `timezone_data_missing`, exit 2 |
| `"0,5"` e `"0.5"` | ambos 0,5; `"1.234,5"` aceito como 1234,5; `"1,234.5"` rejeitado como ambíguo; `"1.234"` (um único ponto seguido de exatamente 3 dígitos, sem vírgula, com parte inteira de 1–3 dígitos diferente de `0`) rejeitado como `ambiguous_decimal` (pode ser 1234 em pt-BR ou 1,234); `"0.125"` é aceito como 0,125 (parte inteira `0` não forma grupo de milhar válido); notação científica (`e`/`E`) rejeitada na CLI como `invalid_input` |
| Intervalo com fim ≤ início ou agenda com sobreposição | `invalid_interval` / `overlapping_intervals` |
| Cruzamento da troca de vigência (ex.: 2026-07-03 → 07-04, real; ou 2027-07-03 → 07-04, sem registro seguinte) | dividido por vigência; cada fatia usa sua tarifa; sem registro na segunda ⇒ erro, ou projeção só com D10 |
| Horário de verão | `zoneinfo` aplicado; o Brasil não tem DST desde 2019, mas o código não presume isso (teste com um `ZoneInfo` construído a partir de uma fixture TZif de teste, rotulada fictícia); offset fixo UTC-3 está descartado (D1) |
| CSV de tarifa com HTML/CAPTCHA | `unexpected_html`, cache anterior preservado |
| CSV truncado (bytes ≠ `Content-Length`) / cabeçalho renomeado | `download_incomplete` / `schema_mismatch`; arquivo vai para quarentena, cache bom intocado |
| Sem rede e cache vencido | sem flag: `network_unavailable` com idade do cache; com `--permitir-cache-vencido`: usa o cache, saída traz `stale: true`, idade e vigência |
| Cache envenenado (hash no índice ≠ arquivo) | `cache_corrupted`, recarrega |
| Município ambíguo/sem cobertura | `ambiguous` com candidatos / `unsupported`, nunca chute |

## Cenários de teste e matriz de aceitação

Nenhum destes testes foi executado: estão definidos para a fase de implementação. Os probes de `requirements/research.md` são provas de viabilidade, não testes do programa. Entradas "fixture" são recortes reais dos CSVs baixados em 2026-10-19.

| # | Requisito | Entrada | Saída esperada | Tipo |
|---|---|---|---|---|
| A1 | kWh = W×h/1000 | 100 W, 10 h | `1,000 kWh` | unit |
| A2 | Custo | 1 kWh a R$ 0,78938/kWh | `R$ 0,79` (HALF_UP; interno 0.78938) | unit |
| A3 | Arredondamento | 0,125 kWh × R$ 1,00 e 0,135 × 1,00 | `R$ 0,13` e `R$ 0,14` (HALF_UP, não bancário) | unit |
| A4 | Zero físico manual | 0 W por 5 h; 100 W por 0 h | `R$ 0,00` nos dois, sem erro e sem `partial_data` | unit |
| A5 | Inválidos e limites D14 | `-1`, `nan`, `inf`, `1e400`, `100000,001` W, `1,2345` W (4 casas), `87600,0001` h; e aceitos: `100000` W, `87600` h | os inválidos ⇒ `invalid_input`, exit 2, JSON `error.code`; os dois limites exatos ⇒ aceitos | unit/cli |
| A6 | Decimal pt-BR | `"0,5"`; `"1.234,5"`; `"1,234.5"`; `"1.234"`; `"0.125"` | 0.5; 1234.5; erro `ambiguous_decimal`; erro `ambiguous_decimal`; 0.125 (parte inteira `0` não é agrupamento de milhar) | unit |
| A7 | Moeda | 1234.5 BRL | `R$ 1.234,50`; JSON `"1234.50"` (string) | unit |
| A8 | Sem float | AST/grep do pacote `domain` | nenhuma ocorrência de `float(` em dinheiro; `Decimal` em todos os VOs | architecture |
| A9 | Agenda | `[08:00,12:00)` + `[12:00,13:00)` | válido, 5 h; `[08:00,12:00)`+`[11:00,13:00)` ⇒ `overlapping_intervals` | unit |
| A10 | Integração CSV com `--max-gap` explícito | `t0,100`; `t0+1h,200`; `t0+2h,200` (degraus) com `--max-gap 1h` | 300 Wh = `0,300 kWh`; `coverage_duration` 2 h; `excluded_duration` 0; `partial_data: false` | unit |
| A11 | Default de 5 min não cobre amostras de 1 h | a mesma série de A10, SEM `--max-gap` | `insufficient_coverage` (exit 2), nunca `R$ 0,00` | unit/cli |
| A12 | Cobertura parcial | 100 W em 00:00, 00:05, 00:30, 00:35 com `--max-gap 5m` | 16,666… Wh (interno 0,01666… kWh; `0,017 kWh` na apresentação, D6); `coverage_duration` 10 min; `excluded_duration` 25 min (lista `[00:05,00:30)` razão `gap`); `partial_data: true`; custo só da parte coberta | unit |
| A13 | Zero coberto vs sem cobertura | série coberta com `watts = 0` por 10 min / série só com gaps | `R$ 0,00` sem erro / `insufficient_coverage` | unit |
| A14 | Duplicata | mesmo timestamp, mesmo valor / valor distinto | 1 amostra / `csv_conflicting_duplicate` | unit |
| A15 | Energia vs potência | série `energy_wh` acumulada tratada como `watts` | rejeitado pelo cabeçalho (`csv_unknown_columns`) | unit |
| A16 | Seleção B1 real | fixture ELETROPAULO 2026-07-04 (inclui duplicatas, Baixa Renda, SCEE, Base Econômica) em 2026-10-19 | `0.78938 R$/kWh`; critérios e hash na proveniência; 1 registro após dedupe | unit |
| A17 | Dedupe vs ambiguidade | duas linhas idênticas / duas com TE diferente | usa 1 / `tariff_ambiguous` | unit |
| A18 | Unidade | linha em `kW` no mesmo perfil | ignorada; só `MWh` | unit |
| A19 | Fora de vigência | data 2027-07-04, ELETROPAULO sem registro | `tariff_not_in_effect`; com `--projetar-ultima-tarifa` usa 0.78938 com warning `projected_tariff` | unit/cli |
| A20 | Divisão por vigências | fixture real ELETROPAULO; 100 W de 2026-07-03 12:00 a 2026-07-04 12:00 (`America/Sao_Paulo`); e 100 W de 2025-12-31 12:00 a 2026-01-01 12:00 | 1,2 kWh × 0,72518 + 1,2 kWh × 0,78938 = R$ 1,817472 ⇒ `R$ 1,82`; no período partido da REH 3.477, duas fatias de 1,2 kWh × 0,72518 (registros não somados) ⇒ `R$ 1,74` | unit |
| A21 | Schema guard | CSV com coluna renomeada / HTML | `schema_mismatch` / `unexpected_html`, cache anterior intacto | infra |
| A22 | Cache atômico | falha no meio do download | `.part` descartado, cache anterior válido | infra |
| A23 | Offline | sem rede, cache 30 h; com/sem `--permitir-cache-vencido` | `network_unavailable` / uso com `stale:true`, idade 30 h | infra/cli |
| A24 | Mapeamento capital | fixtures IndQual+DEC/FEC reais para 3550308 | `Ambiguous` com ELETROPAULO (199) e CERIS (1); conjunto 12450 em `evidence.conjuntos_sem_agente` | unit |
| A25 | Sucessão histórica | fixture `limite.csv` real do conjunto 6818 (EBO 2000–2010, EPB 2010–2013) + campo `SigAgente` com espaços | só EPB (maior `AnoLimiteQualidade`); sigla sem espaços; CNPJ como chave | unit |
| A26 | Município com 1 agente | fixture de município de agente único | `Resolved` | unit |
| A27 | Cobertura ausente | código IBGE inexistente | `Unsupported` | unit |
| A28 | Persistência | gravar escolha do usuário ELETROPAULO para 3550308 | releitura traz vínculo `user_confirmed` separado do oficial | infra |
| A29 | Tarifa manual all-in | `estimar --potencia 100 --horas 10 --tarifa-manual-total 0,80 --inclui tributos --inclui bandeira` | 1 kWh × 0,80 = `R$ 0,80`; saída lista `inclusoes_declaradas: [tributos, bandeira]` e `tarifa_base` 0.80, `adicional` 0 | cli |
| A30 | Dupla inclusão | `--tarifa-manual-total 0,80 --inclui bandeira --adicional-kwh 0,05 --adicional-tipo bandeira` | `double_inclusion`, exit 2 | cli |
| A31 | Inclusão não declarada | `--tarifa-manual-total 0,80 --adicional-kwh 0,05 --adicional-tipo outro` (sem `--inclui`) | `inclusion_undeclared`, exit 2 | cli |
| A32 | ANEEL + adicional | tarifa automática 0,78938 + `--adicional-kwh 0,05 --adicional-tipo bandeira`, 1 kWh | `taxa_total` 0.83938 ⇒ `R$ 0,84`; saída diz que a base não inclui tributos/bandeiras | unit/cli |
| A33 | Preço zero, negativo e limites | `--tarifa-manual-total 0` / `--tarifa-manual-total=-0,10` / `100,000001` / `0,1234567`; e aceito: `100` | `R$ 0,00` com aviso `zero_rate` / `invalid_input` / `invalid_input` (acima de 100, com 6 casas) / `invalid_input` (7 casas) / aceito | unit/cli |
| A34 | Contrato Metering | cada provider ∈ {manual, csv, rapl-fake, wmi-fake} | passa na mesma suíte `availability()`/`read()`, escopo declarado, nunca zero fabricado | contract |
| A35 | RAPL delta simples | 2 leituras fake do `package-0`: 1000→5000 µJ, dt 1 s, `max_energy_range_uj`=1e10 | delta 4000 µJ em 1 s ⇒ potência média 0,004 W; escopo `cpu_package`; `partial_data: false` | unit |
| A36 | RAPL wrap único | 9e9→100 µJ, `max`=1e10, dt 2 s | `dt_max` 5 s ≥ 2 s; delta (1e10−9e9)+100 = 1 000 000 100 µJ; potência média 500,00005 W ≤ 1000 W ⇒ intervalo válido | unit |
| A37 | RAPL múltiplos wraps possíveis | mesmos contadores de A36, dt 10 s | `dt` > `dt_max` (5 s) ⇒ intervalo excluído `indeterminate_wrap`; se for o único ⇒ `insufficient_coverage` | unit |
| A38 | RAPL reset implausível | 5e9→1e9 µJ, `max`=1e10, dt 1 s | wrap assumido daria 6e9 µJ/s = 6000 W > 1000 W ⇒ excluído `counter_reset_or_invalid` | unit |
| A39 | RAPL salto de relógio | dt monotônico 1 s, dt de parede 10 s | excluído `clock_discontinuity` | unit |
| A40 | RAPL zonas | `intel-rapl:0` name `package-0`, `intel-rapl:0:0` name `core`, `intel-rapl:1` name `psys` | só `package-0` é somado; `core` e `psys` listados como `component` | unit |
| A41 | RAPL sem permissão | `energy_uj` ilegível | `Unavailable(permission_denied)`, nunca 0 | unit (fake) |
| A42 | RAPL desabilitado | `package-0` com `enabled` = 0 | `Unavailable(zone_disabled)` (política conservadora) | unit (fake) |
| A43 | WMI ausente | PowerShell retorna 0 instâncias / classe inexistente | `Unavailable(no_power_meter_provider)` | unit (fake, não é live) |
| A44 | WMI nunca prova sistema no v1 | instância fake com `MeterType` 0, `CurrentReading` válido, sem associação comprovável (v1 não conhece classe de associação); outra com `MeterType` = 1 | `component` explícito nos dois casos; nunca `whole_system_ac` nem `whole_system_unverified` | unit (fake) |
| A45 | WMI leitura duvidosa | instância sem `CurrentReading` (nulo) / sem `UnitModifier` / com `SupportCapabilities` = 8 ou = 256 / leitura negativa | `Unavailable(reading_property_unverified)` / `Unavailable(unit_unknown)` / `Unavailable(only_when_discharging)` (8 e 256 ambos) / `Unavailable(invalid_reading)` | unit (fake) |
| A46 | WMI leitura escalada | instância fake completa: `MeterType` 0, `BaseUnits` com código qualquer (guardado bruto em `base_units_code`, aviso `base_units_not_decoded`), `UnitModifier` -3, `CurrentReading` 150000, `Status` OK | 150 W, escopo `component` (nunca `whole_system_ac`); `CurrentReading` marcada "herdada, não validada em hardware" | unit (fake) |
| A47 | Camadas | import graph | `domain` sem `sqlite3/urllib/os/subprocess/csv`; `application` só `domain` | architecture |
| A48 | CLI | `pc-energy-cost estimar --potencia 100 --horas 10 --tarifa-manual-total 0,78938` | texto pt-BR com `R$ 0,79`; `--json` válido no schema v1 e `schema_version "1"` | cli |
| A49 | Fuso sem dados | carregador de fuso fake levanta `ZoneInfoNotFoundError` | `timezone_data_missing`, exit 2 | unit |
| A50 | Instalação sdist → wheel → venv | `python -m build` (gera o sdist e, a partir dele, o wheel), `python -m venv` limpo, `pip install dist/*.whl`; em outro venv, `pip install dist/*.tar.gz` | nos dois: `pc-energy-cost --help` exit 0 e `python -m pc_energy_cost --help` exit 0 | install |
| A51 | Live ANEEL | rede real, `@pytest.mark.live` | `0.78938` só se o dataset ainda traz a mesma REH; senão atualizar fixture e registrar diferença | live |
| A52 | Live RAPL | máquina com permissão | delta ≥ 0 e escopo `cpu_package`; sem permissão ⇒ `skip` com motivo | live |
| A53 | Live Windows | hardware com medidor | só em Windows real; mocks NÃO contam como live | live_windows |

## Verificação (fase de implementação)

Rodar, na raiz do projeto: `python -m pytest` (suíte padrão; `addopts` exclui `live`, `live_windows` e `install`), `python -m pytest -m live` (opcional, rede), e a verificação de instalação (A50), em ordem: (1) `python -m build` (gera o sdist e, a partir dele, o wheel; exige rede para o isolamento de build ou `--no-isolation` com `setuptools` já instalado), (2) `python -m venv <tmp>/v1` e `<tmp>/v1/bin/pip install dist/*.whl`, (3) `<tmp>/v1/bin/pc-energy-cost --help` e `<tmp>/v1/bin/python -m pc_energy_cost --help` com exit 0, (4) repetir (2) e (3) em `<tmp>/v2` instalando `dist/*.tar.gz` (o sdist) em vez do wheel; no Windows os executáveis ficam em `Scripts\`, e isso só vale como teste se rodado em Windows. Configuração necessária em `pyproject.toml`: extra `dev = ["pytest", "build"]` (o `python -m build` exige o pacote `build`); `[tool.pytest.ini_options]` com `pythonpath = ["src"]` (layout `src/`; alternativa: `pip install -e .`), `testpaths = ["tests"]`, markers `live`, `live_windows` e `install` registrados e `addopts = "-m 'not live and not live_windows and not install'"` (marcadores registrados: `live`, `live_windows`, `install`) para que `python -m pytest` puro nunca toque rede/hardware nem construa pacotes; entry point `[project.scripts] pc-energy-cost = "pc_energy_cost.__main__:main"` (o `__main__` chama `composition`, que monta a CLI). Lint/type-check: o plano adota `python -m compileall src tests` e `python -m pytest` como mínimos; ferramenta adicional (ruff/mypy) é decisão do humano (D1: única dependência de runtime é `tzdata` condicional ao Windows).

## Limites por etapa (compatíveis com o plugin)

Cada etapa de implementação segue o limite do `sdd-step-breakdown`: no máximo ~6–7 arquivos criados/modificados (contando testes, fixtures e `__init__.py` de pacotes novos) e ~10–15 casos de teste por etapa, uma etapa = um commit atômico (feito somente após aprovação humana), camadas internas antes das externas. Contexto por etapa ≤ 200k tokens. Em cada etapa: (a) o campo Files lista caminhos RELATIVOS COMPLETOS, sem abreviações `...`; (b) fixtures e testes vêm listados ANTES do código de produção; (c) o número de etapas é o que o limite de arquivos exigir, não um número pré-fixado: uma etapa que ultrapassa ~7 arquivos deve ser dividida. A divisão fica na seção `## Implementation steps` gerada pelo breakdown. A matriz de aceitação tem 53 linhas (A1–A53, contadas por script); cada linha deve ser coberta por exatamente um teste nomeado nas etapas.

## Riscos externos NÃO verificados (visíveis)

1. Dicionário ANEEL: o texto extraído (`probes/dd-tarifas-extracted.txt`) distingue Tarifa de Aplicação (faturamento) de Base Econômica (cálculo tarifário), o que fecha D5; `requirements/research.md` foi atualizado nesta fase. Continua NÃO verificado pelo dicionário: o significado de `SCEE` e se TUSD/TE de B1 incluem algo além do componente de energia.
2. Os nomes dos 24 municípios da Enel não foram verificados (a página só dá a contagem; nomes em imagem de mapa). O alias "Enel SP" ↔ `ELETROPAULO`/CNPJ `61695227000193` está verificado pela página oficial da Enel (`golpes-e-fraudes.html`, probe suplementar de 2026-10-19T04:20:57Z).
3. `Win32_PowerMeter`: documentação legada (2018); hardware real e Windows 10/11 modernos não testados; o campo exato de leitura, a classe de associação ao `Win32_ComputerSystem` e se há um domínio AC comprovável dependem de verificação adicional (diligence-followup) e de hardware. Por isso D15 proíbe `whole_system_ac` no WMI.
4. RAPL: leitura de `energy_uj` não testada (permissão negada neste Linux, CPU AMD Zen 1); semântica de `enabled` (power capping vs leitura de energia) não verificada, daí a política conservadora `zone_disabled`; `P_MAX_W` = 1000 W e os limites de `dt` são provisórios e não foram medidos.
5. URLs, resource IDs, schema e encoding dos CSVs da ANEEL podem mudar; o produto precisa falhar de forma explícita.
6. O vínculo município↔distribuidora vem de indicadores de qualidade, não de cadastro de concessão, e não tem proporção por unidade consumidora; pode haver distribuidora com área parcial no município.

## Due diligence record

Registro do que a due diligence (sdd-plan-diligence, 2026-10-19; segunda passada após o patch D1/D14/D15) concluiu sobre os fatos externos citados ou adiados por este plano; passes posteriores (incluindo o fact check da implementação) leem esta seção. Nenhum passe pode tratar uma linha daqui como motivo para pular uma verificação: o registro diz o que foi concluído uma vez, não o que é verdade agora. Quem editar à mão o fato correspondente no plano deve **apagar** a linha aqui, não atualizá-la.

- SETTLED: `https://dadosabertos.aneel.gov.br/api/3/action/package_show?id=tarifas-distribuidoras-energia-eletrica` (verified against live CKAN package_show via WebFetch, metadata_modified 2026-10-18T10:06:25; primeira passada)
- SETTLED: `fcf2906c-7c32-4b9b-a637-054e7a5234f4` (format `CSV`, name `tarifas-homologadas-distribuidoras-energia-eletrica.csv`, size 178230008; verified against live CKAN package_show; primeira passada)
- SETTLED: `3f841488-80a8-42f2-a6ca-e0c593b228de` (IndQual, format `CSV`, dataset `db9c9f60-b3b5-4504-9dfe-2637922d53ce`, `package_show?id=indqual-municipio`; verified against live CKAN package_show; primeira passada)
- SETTLED: `fd69e1dd-fd66-4269-b60c-cc0b7eb221b4` (format `CSV`, `indicadores-continuidade-coletivos-limite.csv`, dataset `d5f0712e-62f6-4736-8dff-9991f10758a7`; verified against live CKAN package_show; primeira passada)
- SETTLED: cabeçalho de 17 colunas do CSV de tarifas, 8 do `limite.csv` e 5 do IndQual, todos sem BOM (verified against the downloaded files in `probes/`, bytes iniciais `"Da`; não contra fonte live)
- SETTLED: `Content-Type: text/csv` e `Content-Length: 178230008` no CSV de tarifas, e `text/csv` no IndQual (verified against `probes/probe2.log`, cabeçalhos HTTP reais)
- SETTLED: `Content-Type: text/csv` e `Content-Length: 25865955` no `limite.csv` (verified against `probes/supplement-probe.json`, HEAD feito por `urllib` em 2026-10-19T04:20:57Z e GET parcial por `urllib` em 2026-10-19T04:33:15Z, `probes/supplement-probe-get-limite.json`, ambos pelo orquestrador; NÃO verificado via WebFetch)
- SETTLED: `3550308` = São Paulo/SP (verified against live IBGE API `servicodados.ibge.gov.br/api/v1/localidades/municipios/3550308`)
- SETTLED: `61695227000193` ↔ `Eletropaulo Eletricidade de São Paulo S.A` (verified against live `https://www.enel.com.br/pt-saopaulo/golpes-e-fraudes.html` via WebFetch em 2026-10-19: "Eletropaulo Eletricidade de São Paulo S.A - CNPJ: 61.695.227/0001-93", precedido de "esteja sempre atento ao CNPJ da Enel")
- OPEN (unverified): alias `Enel São Paulo`, a página só traz "ENEL SÃO PAULO" como rótulo de navegação do site; a ligação ao CNPJ é inferida pelo contexto da seção `/pt-saopaulo/`, não por frase explícita
- SETTLED: `Get-CimInstance -Namespace root/CIMV2/power -ClassName Win32_PowerMeter` namespace e classe (verified against Microsoft Learn `previous-versions/windows/desktop/powermeterprov/win32-powermeter`, Namespace `Root\CIMV2\power`, Windows 7+, página arquivada, ms.date 2018-05-31)
- SETTLED: `Win32_PowerMeter : CIM_NumericSensor`; a sintaxe MOF publicada (que diz incluir "all of the inherited properties") lista só `Name`, `DeviceID`, `SupportCapabilities`, `MeterType`, `SamplingPeriod`, `MinimumAveragingInterval`, `MaximumAveragingInterval`, `AveragingInterval`, `MinOperatingBudget`, `MaxOperatingBudget`, `BudgetWriteable`, `BudgetEnabled`, `ConfiguredBudget`, `BaseUnits`, `UnitModifier`, `Hysteresis` (verified against Microsoft Learn win32-powermeter via WebFetch)
- SETTLED: `sint32 CurrentReading` definido em `CIM_NumericSensor` ("Current value indicated by the sensor", read-only) (verified against Microsoft Learn `windows/win32/cimwin32prov/cim-numericsensor` via WebFetch)
- OPEN (unverified): `CurrentReading` em `Win32_PowerMeter`, a página da classe não o lista apesar de dizer listar todas as propriedades herdadas; só a herança de `CIM_NumericSensor` o implica, e nenhuma fonte confirma que o provider o preenche
- SETTLED: `MeterType` `uint32`: `0` = "The measurement data is based on input power", `1` = "based on output power" (verified against Microsoft Learn win32-powermeter e WDK `PMI_MEASUREMENT_TYPE`)
- SETTLED: `UnitModifier` `sint32`, "a value of -3 means that the reading is 0.001 times that of the base unit" (logo `leitura × 10^UnitModifier`); `BaseUnits` `uint16`, "Starting in Windows 7 [...] only supports base units in watts" (verified against Microsoft Learn win32-powermeter)
- OPEN (deferred): valor numérico de `BaseUnits` que significa watts, a Microsoft não publica o código; o plano guarda o código bruto em `base_units_code` com o aviso `base_units_not_decoded` e não o decodifica
- SETTLED: `SamplingPeriod` `uint32`, em milissegundos (verified against Microsoft Learn win32-powermeter)
- OPEN (unverified): codificação de `SupportCapabilities`, a Microsoft o chama de "bitmask" mas lista "values" `SupportMeasurement` 0, `SupportThresholds` 1, `SupportBudgeting` 2, `SupportOnlyWhenDischarging` 8; um valor de máscara 0 não pode ser um bit, então 0/1/2/8 podem ser posições de bit ou valores; o WDK `PMI_REPORTED_CAPABILITIES.Flags` dá os nomes `PMI_CAPABILITIES_SUPPORT_MEASUREMENT` ... `PMI_CAPABILITIES_DISCHARGE_ONLY` sem valores numéricos
- SETTLED: `string Status` em `CIM_NumericSensor` (valores "OK", "Error", "Degraded", "Unknown", "Pred Fail", ...) (verified against Microsoft Learn cim-numericsensor); não listado na página de `Win32_PowerMeter` (mesma ressalva de `CurrentReading`)
- OPEN (unverified): classe de associação `Win32_PowerMeter` ↔ `Win32_ComputerSystem`, a Microsoft diz que o medidor "is associated with the instance of the Win32_ComputerSystem class that represents the system" mas não nomeia classe; o provider documenta só `Win32_PowerMeter` e `Win32_PowerMeterEvent`, e remete ao DMTF DSP1015 1.1.0 (não verificado)
- SETTLED: nenhuma fonte Microsoft lida permite provar que o domínio medido é tomada AC; `MeterType` 0 diz apenas "input power", sem AC/DC (verified against Microsoft Learn win32-powermeter, WDK `PMI_MEASUREMENT_TYPE` e `PMI_REPORTED_CAPABILITIES`); sustenta D15
- SETTLED: `/sys/class/powercap/intel-rapl:<N>/` com `energy_uj`, `max_energy_range_uj`, `name`, `enabled` (path verified against local `probes/probe8.log`; atributos verified against docs.kernel.org powercap, cujo exemplo grafa `/sys/class/power_cap/intel-rapl/intel-rapl:0` e `/sys/devices/virtual/powercap`); o diretório do control type `intel-rapl` também casa com `intel-rapl*` e não tem `name`/`energy_uj`
- SETTLED: subzonas `intel-rapl:j:0`/`intel-rapl:j:1` são "core" e "uncore" do pacote pai; zonas de topo do exemplo são pacotes (`package-0`) (verified against docs.kernel.org powercap)
- SETTLED: a doc do kernel não menciona `psys` nem `dram` nem outra zona de topo não-pacote (verified against docs.kernel.org powercap)
- OPEN (unverified): "`psys` pode sobrepor o package", nenhuma fonte lida cobre `psys`
- SETTLED: `enabled` (rw): "Enable/Disable controls at zone level or for all zones using a control type" (verified against docs.kernel.org powercap)
- OPEN (unverified): se `enabled` = `0` impede ler `energy_uj`, a doc não fala de leitura de contador; o texto aponta para controles de capping, sem afirmar nada sobre o contador
- OPEN (unverified): wrap de `energy_uj` em `max_energy_range_uj`, a doc só diz "Range of the above energy counter in micro-joules" e nada sobre wrap/overflow; a aritmética de wrap do plano é derivação própria
- SETTLED: `zoneinfo` usa a base IANA do sistema ou o pacote `tzdata`; "notably Windows systems, do not have an IANA database available [...] it is recommended to declare a dependency on tzdata"; sem ambos ⇒ `ZoneInfoNotFoundError` (subclasse de `KeyError`) (verified against docs.python.org zoneinfo via WebFetch)
- SETTLED: `tzdata; sys_platform == "win32"` é sintaxe válida de marcador (verified against packaging.python.org dependency-specifiers, exemplo `pywin32; sys_platform == "win32"`); a dependência em si continua PROVISÓRIA (D1), não aprovada por humano
- SETTLED: `python -m build` sem `--sdist`/`--wheel` gera o sdist a partir da raiz e o wheel a partir do sdist, em ambiente isolado por padrão; `--no-isolation` exige dependências de build instaladas à parte (verified against build.pypa.io CLI reference via WebFetch)
- SETTLED: `[tool.pytest.ini_options]` com `pythonpath`, `testpaths`, `markers`, `addopts` (verified against docs.pytest.org reference e customize; primeira passada)
- OPEN (currency): `[tool.pytest.ini_options]`, ainda suportado, mas pytest 9.0 introduziu a tabela nativa `[tool.pytest]`; mantido como está
- OPEN (deferred): backend de build do `pyproject.toml` (`[build-system]`), não especificado no plano

## Implementation steps

Convenções para todas as etapas. Raiz do projeto: `./`; todos os caminhos abaixo são relativos a ela. Não há `CLAUDE.md` no projeto (nem aninhado). Comandos de verificação (do plano, seção "Verificação"): `python -m pytest` (suíte padrão; o `addopts` exclui `live`, `live_windows` e `install`), `python -m pytest <caminho>` para a etapa, `python -m compileall src tests` (lint mínimo adotado pelo plano; ruff/mypy não adotados). Sem `git init` e sem commit sem aprovação humana: "um commit por etapa" é a fronteira lógica. Fixtures de CSV/JSON ANEEL são recortes REAIS extraídos dos arquivos em `diretório privado de planejamento (fora do repositório)/probes/` (nunca inventar valores); a árvore `powercap_fake` e as variantes de teste são sintéticas e rotuladas "fake". Testes antes do código de produção. Todo teste que cobre uma linha da matriz se chama `test_aNN_<descrição>` (ex.: `test_a16_selecao_b1_real`), para o `grep` da etapa 18; cada ID A1–A53 aparece em exatamente uma etapa abaixo. Casos "não numerados" são extras da etapa e não pertencem à matriz. Domínio sem `float` em dinheiro e sem imports de `sqlite3/urllib/os/subprocess/csv`. Os testes não usam `__init__.py` (nomes de arquivo de teste são únicos; `rootdir`/`pythonpath` do pytest bastam). Todo pacote novo em `src/` recebe um `__init__.py` vazio (contado nos arquivos de cada etapa).

Contagem de arquivos por etapa (precisa): E1=7, E2=4, E3=3, E4=5, E5=5, E6=6, E7=7, E8=7, E9=5, E10=7, E11=7, E12=7, E13=7, E14=3, E15=6, E16=4, E17=5, E18=7. Total 18 etapas: nenhuma passa de 7 arquivos nem de ~15 casos; a divisão é imposta pelo limite de arquivos/casos, não por um número pré-fixado.

### Step 1: Scaffold, erros estáveis e unidades
- **Files**:
  - `tests/unit/test_units_money.py` (criar; a parte de dinheiro entra na etapa 2)
  - `pyproject.toml`
  - `src/pc_energy_cost/__init__.py`
  - `src/pc_energy_cost/domain/__init__.py`
  - `src/pc_energy_cost/domain/shared/__init__.py`
  - `src/pc_energy_cost/domain/shared/errors.py`
  - `src/pc_energy_cost/domain/shared/units.py`
- **Do**: Primeiro o teste. `pyproject.toml`: backend `setuptools` (decisão deste breakdown; o plano deixou OPEN), layout `src/` com `[tool.setuptools.packages.find] where=["src"]`, `requires-python >=3.11`, `dependencies = ['tzdata; sys_platform == "win32"']` (D1: única dependência de runtime, condicional ao Windows), extra `dev = ["pytest","build"]`, `[project.scripts] pc-energy-cost = "pc_energy_cost.__main__:main"`, `[tool.pytest.ini_options]` com `pythonpath=["src"]`, `testpaths=["tests"]`, markers `live`, `live_windows`, `install` e `addopts = "-m 'not live and not live_windows and not install'"`. `src/pc_energy_cost/__init__.py`: `__version__`. `errors.py`: `DomainError(code, message)` e subclasses; códigos estáveis e exit codes exatamente como a tabela D13 (exit 2: `invalid_input`, `ambiguous_decimal`, `invalid_interval`, `overlapping_intervals`, `timezone_data_missing`, `double_inclusion`, `inclusion_undeclared`, erros de CSV `csv_*` incluindo `csv_conflicting_duplicate` e `csv_unknown_columns`; exit 3: `supplier_ambiguous`, `unsupported`, `tariff_ambiguous`; exit 4: `tariff_not_found`, `tariff_not_in_effect`, `schema_mismatch`, `unexpected_html`, `download_incomplete`, `cache_corrupted`; exit 5: `network_unavailable`; exit 6: `Unavailable`); `insufficient_coverage` leva um atributo `source ∈ {"csv","counter"}` que decide exit 2 (CSV) ou 6 (contador RAPL). `units.py`: VOs `Watts`, `Wh`, `KWh`, `Duration`, `UnitRateBRLPerKWh` sobre `Decimal` (contexto de 28 dígitos), rejeitando negativo/NaN/∞ (zero válido); limites D14 nos VOs (W ≤ 100 000, 3 casas; h ≤ 87 600, 4 casas; tarifa/adicional ≤ 100, 6 casas); `kWh = W × horas / 1000`; apresentação de kWh com 3 casas `ROUND_HALF_UP` e valor interno sem arredondar preservado.
- **Test** (≈9 casos): A1 (`100 W`, `10 h` ⇒ `1,000 kWh`, interno `1`); não numerados: `Watts(-1)`, NaN, ∞ ⇒ `invalid_input`; 0 W e 0 h válidos; limites exatos (100 000 W, 87 600 h) aceitos e 100 000,001 W / 87 600,0001 h rejeitados no VO; tabela código→exit code de D13 fixada por teste; `insufficient_coverage` com `source="csv"` ⇒ 2 e `source="counter"` ⇒ 6; marcador de `tzdata` presente em `pyproject.toml` (lido com `tomllib`) com a string exata `tzdata; sys_platform == "win32"` e `addopts` contendo `not install`.
- **Verify**: `python -m pytest tests/unit/test_units_money.py` verde; `python -m compileall src tests` sem erro.

### Step 2: Dinheiro e parsing decimal com limites D14
- **Files**:
  - `tests/unit/test_units_money.py` (modificar: acrescentar os casos de dinheiro)
  - `tests/unit/test_parsing.py`
  - `src/pc_energy_cost/domain/shared/money.py`
  - `src/pc_energy_cost/domain/shared/parsing.py`
- **Do**: Primeiro os testes. `money.py`: `MoneyBRL` sobre `Decimal`; arredondamento `ROUND_HALF_UP` a 2 casas só na apresentação e no total (D6); formato `R$ 1.234,50`; JSON como string `"1234.50"`; sem `float`. `parsing.py` (sem `csv`/`os`): `parse_decimal(text)` (pt-BR e JSON; texto ≤ 32 caracteres, senão `invalid_input`; `"0,5"` e `"0.5"` ⇒ 0,5; `"1.234,5"` ⇒ 1234,5; `"1,234.5"` ⇒ `ambiguous_decimal`; `"1.234"` (um ponto, exatamente 3 dígitos, sem vírgula, parte inteira de 1–3 dígitos diferente de `0`) ⇒ `ambiguous_decimal`; `"0.125"` aceito como 0,125; `e`/`E`, `nan`, `inf`, `1e400` ⇒ `invalid_input`; negativo ⇒ `invalid_input`) e as funções com limites D14, sem arredondamento silencioso de entrada: `parse_watts` (0 ≤ W ≤ 100 000, ≤ 3 casas), `parse_hours` (0 ≤ h ≤ 87 600, ≤ 4 casas), `parse_rate` (0 ≤ R$/kWh ≤ 100, ≤ 6 casas), `parse_max_gap` (aceita `5m`, `1h`, `30s`; entre 1 s e 24 h), cada uma ⇒ `invalid_input` fora do limite ou com mais casas.
- **Test** (≈14 casos): A2 (1 kWh × 0,78938 ⇒ `R$ 0,79`, interno 0.78938); A3 (0,125 × 1,00 ⇒ `R$ 0,13` e 0,135 × 1,00 ⇒ `R$ 0,14`, HALF_UP e não bancário); A5 (parametrizado: `-1`, `nan`, `inf`, `1e400`, `100000,001` W, `1,2345` W, `87600,0001` h ⇒ `invalid_input` com código estável; `100000` W e `87600` h aceitos; a parte "exit 2 e JSON `error.code`" é mapeada na etapa 15); A6 (`"0,5"`⇒0.5; `"1.234,5"`⇒1234.5; `"1,234.5"`⇒`ambiguous_decimal`; `"1.234"`⇒`ambiguous_decimal`; `"0.125"`⇒0.125); A7 (1234.5 ⇒ `R$ 1.234,50`, JSON `"1234.50"` string); não numerados: texto de 33 caracteres ⇒ `invalid_input`; `parse_max_gap` 0 s e 24 h 1 s rejeitados, 1 s e 24 h aceitos.
- **Verify**: `python -m pytest tests/unit/test_units_money.py tests/unit/test_parsing.py`; `python -m compileall src tests`.

### Step 3: Agenda e fuso (`zoneinfo`)
- **Files**:
  - `tests/unit/test_schedule.py`
  - `src/pc_energy_cost/domain/energy_estimation/__init__.py`
  - `src/pc_energy_cost/domain/energy_estimation/schedule.py`
- **Do**: Primeiro o teste. `schedule.py`: `load_zone(loader=ZoneInfo)` para `America/Sao_Paulo` que converte `ZoneInfoNotFoundError` em `timezone_data_missing` (D1; nunca offset fixo UTC-3 nem fuso silencioso); `Interval[início,fim)` tz-aware (naive é interpretado em `America/Sao_Paulo`; fim ≤ início ⇒ `invalid_interval`); `Schedule` sem sobreposição (`overlapping_intervals`; intervalos adjacentes são válidos) com duração total em `Duration`. Para o teste de DST: o próprio teste gera bytes TZif fictícios (helper no arquivo de teste, rotulado "fictício", sem fixture nova) e constrói um `ZoneInfo.from_file`, de modo que o código não presume ausência de DST.
- **Test** (≈7 casos): A9 (`[08:00,12:00)` + `[12:00,13:00)` ⇒ válido, 5 h; `[08:00,12:00)` + `[11:00,13:00)` ⇒ `overlapping_intervals`); A49 (loader fake levanta `ZoneInfoNotFoundError` ⇒ `timezone_data_missing`, exit 2); não numerados: fim ≤ início ⇒ `invalid_interval`; duração em dia com troca de DST fictícia usa o fuso, não 24 h fixas; naive interpretado em `America/Sao_Paulo`; offset explícito respeitado.
- **Verify**: `python -m pytest tests/unit/test_schedule.py`; `python -m compileall src tests`.

### Step 4: Modelo de Metering e integração de potência com cobertura
- **Files**:
  - `tests/unit/test_integration.py`
  - `src/pc_energy_cost/domain/metering/__init__.py`
  - `src/pc_energy_cost/domain/metering/model.py`
  - `src/pc_energy_cost/domain/metering/ports.py`
  - `src/pc_energy_cost/domain/energy_estimation/integration.py`
- **Do**: Primeiro o teste. `metering/model.py`: `Sample(timestamp, quantity, unit)` distinguindo potência (W) de energia acumulada (µJ/Wh); `Scope` enum `{whole_system_ac, whole_system_unverified, cpu_package, component, manual, scenario}`; `Available(scope, warnings)`, `Unavailable(reason)`; `ExcludedInterval(start, end, reason ∈ {gap, no_sample, indeterminate_wrap, clock_discontinuity, counter_reset_or_invalid})`. `ports.py`: `MeteringProvider` Protocol (`availability()`, `read()`). `integration.py`: `integrate_power(samples, window_start, window_end, max_gap=5min, method="steps"|"trapezoid", pre_excluded=())` ⇒ resultado com `Wh`, `requested_duration`, `coverage_duration`, `excluded_duration` (lista de intervalos com razão) e `partial_data`. Regras de "Cobertura de medição": degraus (cada amostra vale até a próxima, trapézio opt-in); Δ ≤ `max_gap` é coberta com o valor da amostra anterior; Δ > `max_gap` excluída (razão `gap`) sem interpolar; amostras fora da janela recortadas; `[início, primeira)` excluído com razão `no_sample` (nada se estende para trás); a última amostra cobre `[último, fim)` só se `fim − último ≤ max_gap`, senão excluído (`gap`); `coverage_duration == 0` ⇒ `insufficient_coverage` (`source="csv"`), nunca 0 kWh; watts = 0 coberto é válido; duplicata idêntica ⇒ 1 amostra, mesmo timestamp com valor distinto ⇒ `csv_conflicting_duplicate`; fora de ordem ⇒ ordena e emite aviso; `max_gap` fora de 1 s–24 h ⇒ `invalid_input` (D14). `pre_excluded` permite que o provider RAPL (etapa 13) injete intervalos já excluídos.
- **Test** (≈13 casos): A10 (`t0,100`; `t0+1h,200`; `t0+2h,200` com `max_gap=1h` ⇒ 300 Wh = `0,300 kWh`, `coverage_duration` 2 h, `excluded_duration` 0, `partial_data` false); A11 (a mesma série com o `max_gap` default de 5 min ⇒ `insufficient_coverage`, nunca R$ 0,00; o exit 2 é mapeado na etapa 15); A12 (100 W em 00:00, 00:05, 00:30, 00:35, `max_gap=5m` ⇒ 16,666… Wh interno, `0,017 kWh` na apresentação, cobertura 10 min, excluído 25 min com `[00:05,00:30)` razão `gap`, `partial_data` true); A13 (série coberta com `watts=0` por 10 min ⇒ 0 Wh sem erro / série só com gaps ⇒ `insufficient_coverage`); A14 (mesmo timestamp e mesmo valor ⇒ 1 amostra / valor distinto ⇒ `csv_conflicting_duplicate`); não numerados: `--inicio` antes da primeira amostra ⇒ `no_sample`; última amostra com `fim − último` exatamente igual a `max_gap` coberta e `max_gap + 1 s` excluída; amostras fora da janela recortadas; trapézio opt-in; fora de ordem ⇒ ordenado com aviso; `pre_excluded` somado ao `excluded_duration`; `max_gap` de 0 s e de 24 h 1 s ⇒ `invalid_input`.
- **Verify**: `python -m pytest tests/unit/test_integration.py`; `python -m compileall src tests`.

### Step 5: Domínio TariffCatalog (modelo, seleção B1, dedupe)
- **Files**:
  - `tests/fixtures/aneel/tarifas_eletropaulo.csv`
  - `tests/unit/test_tariff_selection.py`
  - `src/pc_energy_cost/domain/tariff_catalog/__init__.py`
  - `src/pc_energy_cost/domain/tariff_catalog/model.py`
  - `src/pc_energy_cost/domain/tariff_catalog/selection.py`
- **Do**: Fixture REAL do CSV de tarifas (cabeçalho exato de 17 colunas, separador `;`, aspas, UTF-8 sem BOM): linhas ELETROPAULO (CNPJ `61695227000193`) cobrindo as vigências 2025-07-04→2025-12-31 e 2026-01-01→2026-07-03 (REH 3.477/2025, TUSD 432,44 + TE 292,74) e 2026-07-04→2027-07-03 (TUSD 472,42 + TE 316,96), incluindo duplicatas totalmente idênticas, variantes Baixa Renda, SCEE, `Base Econômica` e uma linha em `kW`; mais ao menos uma linha de um segundo CNPJ para o caso `tariff_not_found`. O teste lê o CSV com `csv` (permitido em teste) e monta `TariffRecord`. `model.py`: `Distributor(cnpj, sig_agente, aliases verificados)` (para `61695227000193`: `ELETROPAULO`, alias `Eletropaulo Eletricidade de São Paulo S.A`; "Enel São Paulo" não é alias de busca), `TariffProfile` (D4 com todos os critérios do "Filtro do perfil D4"), `TariffRecord` (TUSD/TE em R$/MWh `Decimal`, vigência inclusiva `[início,fim]`, base, REH, unidades), `ResolvedTariff` (R$/kWh = (TUSD+TE)/1000 e `Provenance`: URL, resource id, `metadata_modified`, `Last-Modified`, `DatGeracaoConjuntoDados`, `fetched_at` UTC, SHA-256, REH, vigência, unidades originais, critérios aplicados, aviso fixo "sem tributos, bandeiras e encargos fixos"). `selection.py`: `select_tariff(records, profile, date)` com filtros do perfil D4, dedupe só de linhas totalmente idênticas, 1 restante ⇒ ok, >1 distintos ⇒ `tariff_ambiguous`, 0 ⇒ `tariff_not_found` (perfil inexistente para o CNPJ) ou `tariff_not_in_effect` (perfil existe, nenhuma vigência cobre a data, inclusive data > maior `DatFimVigencia`); função que lista as vigências do perfil (usada na etapa 7). Nunca somar kW, duplicatas ou períodos.
- **Test** (≈9 casos): A16 (fixture em 2026-10-19 ⇒ `0.78938 R$/kWh`, 1 registro após dedupe, critérios e REH na proveniência); A17 (duas linhas idênticas ⇒ usa 1 / duas com TE diferente ⇒ `tariff_ambiguous`); A18 (linha em `kW` no mesmo perfil ignorada, só `MWh`); não numerados: `tariff_not_found` vs `tariff_not_in_effect`; fronteira 2026-07-03 ⇒ 0.72518 e 2026-07-04 ⇒ 0.78938 (vigência inclusiva); Baixa Renda, SCEE e `Base Econômica` excluídos; os dois registros de mesma REH/valores (período partido) permanecem distintos e nunca somados; data > maior `DatFimVigencia` ⇒ `tariff_not_in_effect`.
- **Verify**: `python -m pytest tests/unit/test_tariff_selection.py`; `python -m compileall src tests`.

### Step 6: Domínio LocationSupplierMapping
- **Files**:
  - `tests/fixtures/aneel/indqual_capital.csv`
  - `tests/fixtures/aneel/limite_recorte.csv`
  - `tests/unit/test_supplier_resolver.py`
  - `src/pc_energy_cost/domain/location_supplier/__init__.py`
  - `src/pc_energy_cost/domain/location_supplier/model.py`
  - `src/pc_energy_cost/domain/location_supplier/resolver.py`
- **Do**: Fixtures REAIS: `indqual_capital.csv` (latin-1/cp1252, 5 colunas, `CodMunicipio` ↔ `IdeConjUnidConsumidoras`, com o município 3550308 e um município de agente único) e `limite_recorte.csv` (UTF-8, 8 colunas, `SigAgente` com espaços à direita, conjunto 6818 com EBO 2000–2010 e EPB 2010–2013, conjunto 12450 sem agente, conjuntos ELETROPAULO e CERIS). `model.py`: `Municipality(ibge_code, name, uf)`, `SupplierLink(municipality, distributor, source, evidence, confidence, user_confirmed)`, resultado `Resolved | Ambiguous(candidates) | Unsupported`. `resolver.py`: função pura sobre estruturas em memória (município↔conjuntos, conjunto↔(CNPJ, sigla, `AnoLimiteQualidade`)); por conjunto usa só o(s) agente(s) do MAIOR `AnoLimiteQualidade` (empate no mesmo ano ⇒ ambos); `strip()` nas siglas; a chave é o CNPJ; conta conjuntos por CNPJ; `evidence = {n_conjuntos, conjuntos_sem_agente, ano_limite_usado}`; vínculo oficial `source="aneel:indqual+dec-fec"`, `confidence="official_indicator_join"`; a escolha do usuário é vínculo separado (`source="user"`, `user_confirmed=True`), nunca mesclado; ≥2 agentes ⇒ `Ambiguous` com candidatos e contagem; nenhum ⇒ `Unsupported`. Sem I/O: o teste lê os fixtures e monta as estruturas.
- **Test** (≈6 casos): A24 (3550308 ⇒ `Ambiguous` com ELETROPAULO 199 conjuntos e CERIS 1; 12450 em `evidence.conjuntos_sem_agente`); A25 (conjunto 6818 ⇒ só EPB, `ano_limite_usado` registrado, sigla sem espaços, CNPJ como chave); A26 (município de agente único ⇒ `Resolved`); A27 (código IBGE inexistente ⇒ `Unsupported`); não numerados: empate de CNPJs no mesmo ano ⇒ ambos candidatos; vínculo `user` permanece separado do oficial.
- **Verify**: `python -m pytest tests/unit/test_supplier_resolver.py`; `python -m compileall src tests`.

### Step 7: Estimativa de custo, tarifa manual/adicional e casos de uso de tarifa
- **Files**:
  - `tests/unit/test_estimate.py`
  - `tests/application/test_estimate_cost.py`
  - `src/pc_energy_cost/domain/energy_estimation/estimate.py`
  - `src/pc_energy_cost/application/__init__.py`
  - `src/pc_energy_cost/application/ports.py`
  - `src/pc_energy_cost/application/resolve_tariff.py`
  - `src/pc_energy_cost/application/estimate_cost.py`
- **Do**: Primeiro os testes (fakes em memória das portas; registros de tarifa do teste vêm do fixture da etapa 5). `estimate.py`: `CostEstimate` (energia interna + apresentada, tarifa usada, custo, avisos, escopo de medição, `requested_duration`, `coverage_duration`, `excluded_duration`, `partial_data`, `inclusoes_declaradas`, `tarifa_base`, `adicional`, `taxa_total`) e divisão do intervalo por vigências (cada fatia usa a tarifa da sua vigência; registros do período partido nunca somados; `Decimal` interno; arredonda só o custo final). `application/ports.py`: Protocols `TariffSource`, `SupplierSource`, `Clock`, `Store` (assinaturas mínimas). `resolve_tariff.py`: tarifa por CNPJ+data via `TariffSource`; D10 (`tariff_not_in_effect`; `projetar_ultima_tarifa` usa a última vigência com aviso `projected_tariff`); política de "Tarifa manual e adicionais": `--tarifa-manual-total` all-in com `--inclui` ∈ {`tributos`,`bandeira`,`encargos`,`nao-declarado` (default)}, `--adicional-kwh` exige `--adicional-tipo ∈ {bandeira,tributos,outro}`, adicional de tipo (`bandeira`/`tributos`) já em `--inclui` ⇒ `double_inclusion`, adicional com `nao-declarado` ⇒ `inclusion_undeclared` (tipo `outro` só passa com `--inclui` explícito), tarifa ANEEL + adicional permitido e somado com aviso de que a base não inclui tributos/bandeiras, `--adicional-tipo` sem `--adicional-kwh` ou `nao-declarado` combinado com outro `--inclui` ⇒ `invalid_input`, preço negativo ⇒ `invalid_input`, zero ⇒ válido com aviso `zero_rate`, limites D14 de preço (0–100, ≤ 6 casas), `taxa_total = tarifa_base + adicional` em `Decimal`, encargos fixos nunca rateados. `estimate_cost.py`: orquestra potência média / resultado de integração / `--cenario-potencia-nominal W` (rotulado `scenario`, D12, nunca telemetria) × agenda × tarifa ⇒ `CostEstimate`.
- **Test** (≈14 casos): A4 (0 W por 5 h e 100 W por 0 h ⇒ `R$ 0,00`, sem erro e `partial_data` false); A19 (2027-07-04 sem registro ⇒ `tariff_not_in_effect`; com projeção usa 0.78938 e aviso `projected_tariff`); A20 (100 W de 2026-07-03 12:00 a 2026-07-04 12:00 ⇒ 1,2 × 0,72518 + 1,2 × 0,78938 = 1,817472 ⇒ `R$ 1,82`; 100 W de 2025-12-31 12:00 a 2026-01-01 12:00 ⇒ duas fatias de 1,2 kWh × 0,72518 ⇒ `R$ 1,74`); A29 (100 W, 10 h, manual 0,80, `inclui tributos+bandeira` ⇒ `R$ 0,80`, `inclusoes_declaradas [tributos, bandeira]`, `tarifa_base` 0.80, `adicional` 0); A30 (manual 0,80 + `inclui bandeira` + adicional 0,05 tipo `bandeira` ⇒ `double_inclusion`); A31 (manual 0,80 + adicional 0,05 tipo `outro`, sem `inclui` ⇒ `inclusion_undeclared`); A32 (ANEEL 0,78938 + adicional 0,05 `bandeira`, 1 kWh ⇒ `taxa_total` 0.83938 ⇒ `R$ 0,84`, aviso de base sem tributos/bandeiras); A33 (parametrizado: `0` ⇒ `R$ 0,00` com `zero_rate`; `-0,10`, `100,000001`, `0,1234567` ⇒ `invalid_input`; `100` aceito; a forma `--opcao=-0,10` do argparse é testada na etapa 15); não numerados: cenário nominal rotulado `scenario`; `--adicional-tipo` sem `--adicional-kwh` ⇒ `invalid_input`; cobertura parcial propagada da integração para `partial_data`.
- **Verify**: `python -m pytest tests/unit/test_estimate.py tests/application/test_estimate_cost.py`; `python -m compileall src tests`.

### Step 8: Cliente CKAN e fixtures `package_show`
- **Files**:
  - `tests/fixtures/aneel/package_show_tarifas.json`
  - `tests/fixtures/aneel/package_show_indqual.json`
  - `tests/fixtures/aneel/package_show_decfec.json`
  - `tests/infrastructure/test_ckan.py`
  - `src/pc_energy_cost/infrastructure/__init__.py`
  - `src/pc_energy_cost/infrastructure/aneel/__init__.py`
  - `src/pc_energy_cost/infrastructure/aneel/ckan.py`
- **Do**: Fixtures são respostas REAIS do CKAN (copiadas de `probes/`; os recursos `fcf2906c-7c32-4b9b-a637-054e7a5234f4`, `3f841488-80a8-42f2-a6ca-e0c593b228de` e `fd69e1dd-fd66-4269-b60c-cc0b7eb221b4` existem nelas). `ckan.py`: `resolve_resource(package_json, resource_id, fallback_name_contains=None)` e `package_show(fetch, package_id)` com `fetch` injetado (o teste não usa rede nem o fetcher da etapa 9): escolhe o recurso por `id`; fallback somente se houver um único recurso `format == CSV` cujo nome contém `tarifas-homologadas`; ambíguo ou ausente ⇒ erro explícito (`schema_mismatch`); devolve URL do recurso, `metadata_modified` e o `resource id`.
- **Test** (≈6 casos): escolha por id nos três pacotes (tarifas, IndQual, DEC/FEC) devolve URL e `metadata_modified` esperados; id desconhecido sem fallback ⇒ erro; fallback com exatamente um CSV `tarifas-homologadas` funciona; fallback com dois candidatos ⇒ erro (nunca escolhe); JSON sem a chave `result` ⇒ `schema_mismatch`. Sem IDs A (nenhuma linha da matriz é específica do CKAN).
- **Verify**: `python -m pytest tests/infrastructure/test_ckan.py`; `python -m compileall src tests`.

### Step 9: Fetcher HTTP e cache de arquivo
- **Files**:
  - `tests/infrastructure/test_fetcher_cache.py`
  - `src/pc_energy_cost/infrastructure/http/__init__.py`
  - `src/pc_energy_cost/infrastructure/http/fetcher.py`
  - `src/pc_energy_cost/infrastructure/cache/__init__.py`
  - `src/pc_energy_cost/infrastructure/cache/file_cache.py`
- **Do**: Primeiro o teste (servidor HTTP local com `http.server` em thread; sem rede real). `fetcher.py` (urllib): timeout de conexão 30 s / total 300 s (configuráveis nos testes), cap 300 MB, aceita gzip, `Content-Type` exigido `text/csv` para os TRÊS CSVs (qualquer outro, ex. HTML ⇒ `unexpected_html`; sem lista alternativa por recurso), bytes recebidos ≠ `Content-Length` ou conexão cortada ⇒ `download_incomplete`, falha de rede ⇒ `network_unavailable`, SHA-256 em streaming, escrita em `.part`. `file_cache.py`: `.part` + `os.replace` atômico, hash, TTL 24 h (D7), validador injetado (ex.: schema guard) cujo `schema_mismatch` leva o arquivo à quarentena sem tocar o cache bom, `cache_corrupted` quando o hash do índice ≠ arquivo, idade do cache disponível para `network_unavailable`/stale.
- **Test** (≈11 casos): A21 (servidor devolve HTML ⇒ `unexpected_html` e cache anterior intacto; validador injetado levanta `schema_mismatch` ⇒ arquivo em quarentena e cache anterior intacto; o schema guard real dos CSVs é testado na etapa 10); A22 (conexão cortada no meio do download ⇒ `.part` descartado e cache anterior válido); não numerados: `Content-Length` maior que o corpo ⇒ `download_incomplete`; `text/plain` rejeitado; gzip aceito; cap de bytes excedido; timeout ⇒ `network_unavailable`; SHA-256 calculado confere; cache envenenado (hash do índice ≠ arquivo) ⇒ `cache_corrupted`; TTL 24 h vencido detectado; idade do cache informada.
- **Verify**: `python -m pytest tests/infrastructure/test_fetcher_cache.py`; `python -m compileall src tests`.

### Step 10: Parsers CSV ANEEL e SQLite store
- **Files**:
  - `tests/infrastructure/test_tariff_csv.py`
  - `tests/infrastructure/test_supplier_csv.py`
  - `tests/infrastructure/test_sqlite_store.py`
  - `src/pc_energy_cost/infrastructure/persistence/__init__.py`
  - `src/pc_energy_cost/infrastructure/aneel/tariff_csv.py`
  - `src/pc_energy_cost/infrastructure/aneel/supplier_csv.py`
  - `src/pc_energy_cost/infrastructure/persistence/sqlite_store.py`
- **Do**: Primeiro os testes (usam os fixtures das etapas 5 e 6). `tariff_csv.py`: parser streaming `utf-8-sig` (com e sem BOM), `;`, aspas, schema guard com EXATAMENTE as 17 colunas do CSV real (faltando/renomeada ⇒ `schema_mismatch`), decimal pt-BR por `Decimal` (aceita `,00`), linhas normalizadas com valores como texto. `supplier_csv.py`: IndQual (latin-1/cp1252, 5 colunas) e `limite.csv` (`utf-8-sig`, 8 colunas), schema guard por arquivo, `strip()` em todos os campos texto, estruturas entregues ao resolver da etapa 6. `sqlite_store.py` (`sqlite3`): migrações versionadas; tabela de tarifas indexada por `(NumCNPJDistribuidora, DatInicioVigencia, DatFimVigencia)` com hash do arquivo de origem (o `estimar` nunca re-parseia os 178 MB); vínculos oficiais e `user_confirmed` em registros separados; preferências; índice do cache; carga em transação (falha ⇒ rollback, dados anteriores intactos); implementa `TariffSource`/`SupplierSource`/`Store` de `application/ports.py`.
- **Test** (≈11 casos): A28 (gravar a escolha do usuário ELETROPAULO para 3550308 ⇒ releitura traz o vínculo `user_confirmed` separado do oficial); não numerados: schema guard (coluna renomeada e coluna faltando) para os três CSVs, com e sem BOM; `,00` e decimais pt-BR parseados; consulta por CNPJ+data devolve os mesmos registros do fixture; carga que falha no meio faz rollback e preserva a carga anterior; migração cria o schema versionado; `strip()` das siglas no `limite_recorte.csv`.
- **Verify**: `python -m pytest tests/infrastructure/test_tariff_csv.py tests/infrastructure/test_supplier_csv.py tests/infrastructure/test_sqlite_store.py`; `python -m compileall src tests`.

### Step 11: Casos de uso refresh_catalog, resolve_supplier, measure_power e contrato TariffSource
- **Files**:
  - `tests/application/test_refresh_catalog.py`
  - `tests/application/test_resolve_supplier.py`
  - `tests/application/test_measure_power.py`
  - `tests/contract/test_tariff_source_contract.py`
  - `src/pc_energy_cost/application/refresh_catalog.py`
  - `src/pc_energy_cost/application/resolve_supplier.py`
  - `src/pc_energy_cost/application/measure_power.py`
- **Do**: Primeiro os testes (fakes das portas; o contrato `TariffSource` roda sobre um fake em memória e sobre o `sqlite_store` da etapa 10 carregado do fixture). `refresh_catalog.py`: orquestra CKAN ⇒ fetch ⇒ cache ⇒ parse streaming UMA vez ⇒ grava no store (tarifas e as duas fontes município/distribuidora, rotulado "parcial / indicativo"); respeita o TTL de 24 h; offline sem flag ⇒ `network_unavailable` com a idade do cache; com `permitir_cache_vencido` ⇒ usa o cache, resultado traz `stale: true`, idade e vigência; falha preserva o cache anterior. `resolve_supplier.py`: IBGE ⇒ `Resolved|Ambiguous|Unsupported`; D8 (`--distribuidora <CNPJ>` ou escolha interativa em TTY via porta injetada; não-TTY ou `--json` ⇒ `supplier_ambiguous` com candidatos, nunca pergunta); persiste a escolha do usuário separada do oficial; sem "predominante" automático. `measure_power.py`: consulta `MeteringProvider.availability()`; `Unavailable` ⇒ erro de telemetria (exit 6), nunca zero fabricado; `insufficient_coverage` de contador ⇒ exit 6.
- **Test** (≈12 casos): A23 (cache de 30 h e sem rede: sem a flag ⇒ `network_unavailable` com idade; com `permitir_cache_vencido` ⇒ usa o cache com `stale:true` e idade 30 h); não numerados: D8 com TTY (escolha pela porta), sem TTY ⇒ `supplier_ambiguous` com candidatos, `--distribuidora <CNPJ>` resolve, `--json` nunca pergunta; persistência da escolha separada; refresh que falha no meio mantém o cache anterior; refresh dentro do TTL não baixa de novo; `Unavailable` propaga sem zero; `insufficient_coverage` de contador ⇒ exit 6; contrato `TariffSource` idêntico no fake e no SQLite.
- **Verify**: `python -m pytest tests/application tests/contract/test_tariff_source_contract.py`; `python -m compileall src tests`.

### Step 12: Providers manual e série CSV
- **Files**:
  - `tests/fixtures/metering/serie_valida.csv`
  - `tests/fixtures/metering/serie_gap.csv`
  - `tests/fixtures/metering/serie_invalida.csv`
  - `tests/infrastructure/test_metering_manual_csv.py`
  - `src/pc_energy_cost/infrastructure/metering/__init__.py`
  - `src/pc_energy_cost/infrastructure/metering/manual.py`
  - `src/pc_energy_cost/infrastructure/metering/csv_series.py`
- **Do**: Fixtures de série (sintéticas, rotuladas): `serie_valida.csv` (`timestamp,watts`, ISO-8601 com offset e naive), `serie_gap.csv` (amostras com gaps maiores que o `max_gap` default), `serie_invalida.csv` (linhas com watts inválido, timestamp inválido e colunas erradas). `manual.py`: `ManualAverageWatts` (`parse_watts` da etapa 2; 0 W válido; escopo `manual`). `csv_series.py` (`csv`): cabeçalho exato `timestamp,watts` (outras colunas, ex. `energy_wh` ⇒ `csv_unknown_columns`); timestamp ISO-8601 com offset ou naive interpretado em `America/Sao_Paulo`; linha inválida ⇒ erro com número da linha; limites D14 por linha (watts 0–100 000, ≤ 3 casas); CSV de medição ≤ 1 000 000 linhas (excedido ⇒ erro de CSV); devolve `Sample`s para `integrate_power`; escopo `manual`.
- **Test** (≈10 casos): A15 (série com cabeçalho `timestamp,energy_wh` tratada como watts ⇒ rejeitada com `csv_unknown_columns`); não numerados: série válida lida com offset e naive; linha inválida ⇒ erro com número da linha; watts negativo/NaN/acima de 100 000/4 casas por linha ⇒ `invalid_input`; 1 000 001 linhas ⇒ erro (gerado em memória, sem arquivo); `serie_gap.csv` com `max_gap` default produz `partial_data` ou `insufficient_coverage` via `integrate_power`; manual 0 W válido, manual negativo ⇒ `invalid_input`; escopo `manual` declarado.
- **Verify**: `python -m pytest tests/infrastructure/test_metering_manual_csv.py`; `python -m compileall src tests`.

### Step 13: Provider Linux RAPL
- **Files**:
  - `tests/fixtures/metering/powercap_fake/intel-rapl:0/name`
  - `tests/fixtures/metering/powercap_fake/intel-rapl:0/energy_uj`
  - `tests/fixtures/metering/powercap_fake/intel-rapl:0/max_energy_range_uj`
  - `tests/fixtures/metering/powercap_fake/intel-rapl:0/enabled`
  - `tests/fixtures/metering/powercap_fake/intel-rapl:0:0/name`
  - `tests/infrastructure/test_metering_rapl.py`
  - `src/pc_energy_cost/infrastructure/metering/linux_rapl.py`
- **Do**: Fixture sintética rotulada fake (baseline: `intel-rapl:0` com `name`=`package-0`, `enabled`=1, `max_energy_range_uj`=`10000000000`, `energy_uj` inicial; `intel-rapl:0:0` com `name`=`core`); as variantes (zona `psys` em `intel-rapl:1`, `enabled`=0, `energy_uj` ilegível, contadores de wrap/reset) o teste cria em `tmp_path` a partir de cópia do baseline. `linux_rapl.py`: raiz do sysfs, relógio monotônico (`time.monotonic_ns()`) e relógio de parede injetáveis, nunca sudo. Zonas somadas: só diretórios `intel-rapl:<N>` (sem segundo `:`) cujo `name` casa `^package-[0-9]+$`; qualquer outra zona de topo (`psys`, `dram`) e toda subzona (`intel-rapl:<N>:<M>`) listadas como `component`, nunca somadas. Indisponibilidade, nunca zero: `energy_uj`/`max_energy_range_uj` ilegível ou `PermissionError` ⇒ `Unavailable(permission_denied)`; `enabled`=0 ⇒ `Unavailable(zone_disabled)` (política conservadora provisória); sem `/sys/class/powercap` ou sem `package-N` ⇒ `Unavailable(no_rapl_zone)`; valor não numérico ou `max_energy_range_uj` ≤ 0 ⇒ `Unavailable(invalid_counter)`. Política de amostragem/wrap/reset (conservadora, provisória, não medida): `P_MAX_W` = 1000 W por package (`--rapl-max-watts`, 1 ≤ valor ≤ 10 000, fora ⇒ `invalid_input`); `dt_max = max_energy_range_uj / (2 × P_MAX_W × 1 000 000)` s, limitado a 60 s e piso 0,5 s; intervalo de amostragem `min(dt_max, 5 s)`; para cada par (anterior, atual): (1) `dt` monotônico > `dt_max` ⇒ excluído `indeterminate_wrap`; (2) |`dt` monotônico − `dt` de parede| > 2 s ⇒ excluído `clock_discontinuity`; (3) `atual ≥ anterior` ⇒ delta = diferença; (4) `atual < anterior` ⇒ UM wrap: delta = `atual + max_energy_range_uj − anterior`; (5) potência média = delta/dt; > `P_MAX_W` ⇒ excluído `counter_reset_or_invalid`; (6) excluídos entram em `excluded_duration`/`partial_data` (via `pre_excluded` de `integrate_power`), todos excluídos ⇒ `insufficient_coverage` (`source="counter"`, exit 6). Escopo `cpu_package`, nunca `whole_system_ac`.
- **Test** (≈15 casos): A35 (1000→5000 µJ, dt 1 s, max 1e10 ⇒ delta 4000 µJ, 0,004 W, `cpu_package`, `partial_data` false); A36 (9e9→100 µJ, max 1e10, dt 2 s ⇒ `dt_max` 5 s, delta 1 000 000 100 µJ, 500,00005 W ≤ 1000 W, válido); A37 (mesmos contadores, dt 10 s ⇒ `indeterminate_wrap`; único intervalo ⇒ `insufficient_coverage`); A38 (5e9→1e9, dt 1 s ⇒ 6000 W > 1000 W ⇒ `counter_reset_or_invalid`); A39 (monotônico 1 s, parede 10 s ⇒ `clock_discontinuity`); A40 (`intel-rapl:0` `package-0`, `intel-rapl:0:0` `core`, `intel-rapl:1` `psys` ⇒ só `package-0` somado; `core` e `psys` como `component`); A41 (`energy_uj` ilegível ⇒ `Unavailable(permission_denied)`, nunca 0); A42 (`enabled`=0 ⇒ `Unavailable(zone_disabled)`); não numerados: `no_rapl_zone`; `invalid_counter` (texto e `max` ≤ 0); `dt_max` com piso 0,5 s e teto 60 s; `--rapl-max-watts` 0 e 10 001 ⇒ `invalid_input`; dois packages somados; dram de topo não somada.
- **Verify**: `python -m pytest tests/infrastructure/test_metering_rapl.py`; `python -m compileall src tests`.

### Step 14: Provider Windows WMI (somente fakes) e contrato do Metering
- **Files**:
  - `tests/infrastructure/test_metering_wmi.py`
  - `tests/contract/test_metering_provider_contract.py`
  - `src/pc_energy_cost/infrastructure/metering/windows_wmi.py`
- **Do**: Primeiro os testes (executor de comando injetável, saídas fake de `Get-CimInstance`; nada roda PowerShell de verdade; "Nunca testado em Windows"). `windows_wmi.py`: comando fixo `powershell.exe -NoProfile -NonInteractive -Command` com `Get-CimInstance -Namespace root/CIMV2/power -ClassName Win32_PowerMeter`, somente leitura, timeout 10 s, sem interpolação de entrada do usuário; nunca escreve `ConfiguredBudget`, `BudgetEnabled`, `AveragingInterval`. Condições (D15): classe ausente ou 0 instâncias ⇒ `Unavailable(no_power_meter_provider)`; `CurrentReading` ausente/nulo/não numérico ⇒ `Unavailable(reading_property_unverified)` (propriedade herdada de `CIM_NumericSensor`, não validada em hardware); `UnitModifier` ou `BaseUnits` ausente ⇒ `Unavailable(unit_unknown)`; leitura = `CurrentReading × 10^UnitModifier` em `Decimal`; `BaseUnits` guardado bruto em `base_units_code` com aviso `base_units_not_decoded` (não decodifica); `SupportCapabilities & 0x8` ou `& 0x100` ⇒ `Unavailable(only_when_discharging)` (`SupportMeasurement` não testado como flag); `Status` ≠ "OK" quando exposto, leitura negativa ou > 100 000 W ⇒ `Unavailable(invalid_reading)`, `Status` ausente aceito com aviso `status_not_exposed`; `SamplingPeriod` (ms) respeitado, leitura repetida dentro do período não conta como amostra nova; `MeterType` 0 ou 1/ausente (1/ausente rotulado "potência de saída/desconhecida"). No v1 a associação a `Win32_ComputerSystem` não é comprovável: TODA instância sai como `component`, NUNCA `whole_system_ac` e nem `whole_system_unverified` (reservado para plano revisado/hardware validado); nunca zero fabricado nem escala de CPU para PC inteiro. Contrato: suíte única parametrizada sobre `ManualAverageWatts`, `CsvPowerSeries`, RAPL-fake (baseline da etapa 13 via `tmp_path`) e WMI-fake.
- **Test** (≈13 casos): A34 (os quatro providers passam a mesma suíte `availability()`/`read()`, declaram escopo e nunca fabricam zero); A43 (0 instâncias / classe inexistente ⇒ `Unavailable(no_power_meter_provider)`); A44 (`MeterType` 0 com `CurrentReading` válido e sem associação comprovável, e `MeterType` 1 ⇒ `component` nos dois; nunca `whole_system_ac` nem `whole_system_unverified`); A45 (parametrizado: `CurrentReading` nulo ⇒ `reading_property_unverified`; sem `UnitModifier` ⇒ `unit_unknown`; `SupportCapabilities` 8 e 256 ⇒ `only_when_discharging`; leitura negativa ⇒ `invalid_reading`); A46 (`MeterType` 0, `BaseUnits` qualquer, `UnitModifier` −3, `CurrentReading` 150000, `Status` OK ⇒ 150 W, `component`, `base_units_code` bruto, aviso `base_units_not_decoded`, leitura marcada "herdada, não validada em hardware"); não numerados: `Status` ausente ⇒ aviso `status_not_exposed`; leitura > 100 000 W ⇒ `invalid_reading`; comando fixo sem interpolação e timeout de 10 s; nenhuma escrita em propriedades graváveis; leitura repetida dentro do `SamplingPeriod` não gera amostra nova.
- **Verify**: `python -m pytest tests/infrastructure/test_metering_wmi.py tests/contract/test_metering_provider_contract.py`; `python -m compileall src tests`.

### Step 15: Interface CLI (argparse, render pt-BR, schema JSON v1)
- **Files**:
  - `tests/cli/test_cli_end_to_end.py` (criar, com serviços injetados fake)
  - `src/pc_energy_cost/interface/__init__.py`
  - `src/pc_energy_cost/interface/cli/__init__.py`
  - `src/pc_energy_cost/interface/cli/json_schema.py`
  - `src/pc_energy_cost/interface/cli/render_pt.py`
  - `src/pc_energy_cost/interface/cli/main.py`
- **Do**: Primeiro o teste. `main.py` (argparse): `run(argv, services, stdin_is_tty)` com serviços injetados (sem importar `composition`); subcomandos `estimar` (`--potencia`, `--horas`, `--inicio/--fim`, `--serie-csv`, `--max-gap`, `--trapezio`, `--municipio`, `--distribuidora`, `--tarifa-manual-total`, `--inclui`, `--adicional-kwh`, `--adicional-tipo`, `--projetar-ultima-tarifa`, `--cenario-potencia-nominal`, `--rapl-max-watts`, `--permitir-cache-vencido`, `--json`) e `atualizar-catalogo`; `DomainError` ⇒ exit code da tabela D13; erros de uso do `argparse` convertidos em `invalid_input` (exit 2, com `error.code` em `--json`); `--json` nunca faz prompt. `render_pt.py`: texto pt-BR (`1,000 kWh`, `R$ 0,79`, avisos, escopo, proveniência, idade/`stale`, `coverage_duration`/`excluded_duration`/`partial_data`, `inclusoes_declaradas`, composição `tarifa_base`/`adicional`/`taxa_total`, rótulo "estimativa da energia atribuível, não fatura"). `json_schema.py`: schema v1 (`schema_version: "1"`, dinheiro como string, `error.code`) e validador mínimo stdlib.
- **Test** (≈14 casos; todos não numerados, pois as linhas A da CLI são tratadas nas etapas 2, 4 e 16): tabela D13 completa (cada código ⇒ exit esperado); `invalid_input` ⇒ exit 2 e `error.code` em `--json` (parte CLI de A5); `insufficient_coverage` de CSV ⇒ exit 2 (parte CLI de A11) e de contador ⇒ exit 6; `Unavailable` ⇒ exit 6; ambiguidade sem TTY com `--json` ⇒ `supplier_ambiguous` exit 3 com candidatos e sem prompt; `--opcao=-0,10` ⇒ `invalid_input` (usar a forma com `=`); `--projetar-ultima-tarifa` emite `projected_tariff`; saída JSON validada pelo schema v1; texto lista `inclusoes_declaradas` e a composição da taxa; stale mostra idade e vigência.
- **Verify**: `python -m pytest tests/cli`; `python -m compileall src tests`.

### Step 16: Composição, `__main__` e arquitetura
- **Files**:
  - `tests/architecture/test_layering.py`
  - `tests/cli/test_cli_end_to_end.py` (modificar: acrescentar casos com a composição real)
  - `src/pc_energy_cost/composition.py`
  - `src/pc_energy_cost/__main__.py`
- **Do**: Primeiro os testes. `test_layering.py`: grafo de imports via `ast`: `domain` só importa `domain` e stdlib pura (sem `sqlite3`, `urllib`, `os`, `subprocess`, `csv`), `application` só `domain`, `infrastructure`/`interface` só `application`/`domain`, apenas `composition.py` importa tudo; varredura do pacote `domain` sem `float(` em dinheiro e com `Decimal` nos VOs. `composition.py`: único módulo que monta adaptadores (store SQLite com caminho configurável por variável de ambiente/argumento, fetcher, cache, providers) e casos de uso. `__main__.py`: `main()` chama `composition` e `interface.cli.main.run`; `python -m pc_energy_cost` equivale ao entry point.
- **Test** (≈6 casos): A8 (nenhuma ocorrência de `float(` em dinheiro no pacote `domain`; VOs com `Decimal`); A47 (grafo de imports respeita as camadas); A48 (`estimar --potencia 100 --horas 10 --tarifa-manual-total 0,78938` pela composição real, store SQLite temporário e fontes fake, sem rede ⇒ texto pt-BR com `R$ 0,79`; `--json` válido no schema v1 com `schema_version "1"`); não numerados: `atualizar-catalogo` com fontes fake grava no store; `python -m pc_energy_cost --help` exit 0.
- **Verify**: `python -m pytest` (suíte padrão completa); `python -m compileall src tests`; `python -m pc_energy_cost --help` exit 0.

### Step 17: Testes live e instalação sdist → wheel → venv limpo
- **Files**:
  - `tests/install/test_install.py`
  - `tests/live/test_live_aneel.py`
  - `tests/live/test_live_linux_rapl.py`
  - `tests/live/test_live_windows_wmi.py`
  - `pyproject.toml` (modificar somente se o build/instalação falharem, para corrigir pacotes `src/`, entry point ou metadados)
- **Do**: Primeiro os testes. `test_install.py` (marcador `install`, excluído do `addopts` padrão): `python -m build` (sdist e, a partir dele, wheel; exige rede para isolamento ou `--no-isolation` com `setuptools` instalado), `python -m venv` limpo `v1`, `pip install dist/*.whl`; em `v2`, `pip install dist/*.tar.gz`; nos dois executa `pc-energy-cost --help` e `python -m pc_energy_cost --help`; confere nos metadados do wheel o `Requires-Dist: tzdata; sys_platform == "win32"` (D1). No Windows os executáveis ficam em `Scripts\`, e isso só vale se rodado em Windows. `test_live_aneel.py` (marcador `live`, rede real), `test_live_linux_rapl.py` (marcador `live`, `skip` com motivo sem permissão), `test_live_windows_wmi.py` (marcador `live_windows`, `skip` fora de Windows com hardware; mocks NÃO contam como live). Não afirmar que os live passaram se foram skipped/não executados.
- **Test** (4 casos): A50 (sdist → wheel → venv limpo: nos dois instalados, `pc-energy-cost --help` exit 0 e `python -m pc_energy_cost --help` exit 0, mais o `Requires-Dist` condicional do `tzdata`); A51 (live ANEEL: `0.78938` só se o dataset ainda traz a mesma REH; senão atualizar o fixture e registrar a diferença); A52 (live RAPL: delta ≥ 0 e escopo `cpu_package`; sem permissão ⇒ `skip` com motivo); A53 (live Windows: só em Windows real com medidor; `skip` caso contrário).
- **Verify**: `python -m pytest` (não toca rede/hardware/build); `python -m pytest -m install` (rede para o build isolado); `python -m pytest -m live` (opcional, rede); `python -m build` e a instalação manual equivalente em venv novo com `pc-energy-cost --help` exit 0.

### Step 18: Documentação e matriz requisitos-testes
- **Files**:
  - `README.md`
  - `docs/arquitetura.md`
  - `docs/fontes-de-dados.md`
  - `docs/telemetria.md`
  - `docs/extensoes.md`
  - `docs/checklist-instalacao.md`
  - `docs/matriz-requisitos-testes.md`
- **Do**: pt-BR. `README.md`: instalação (incluindo `tzdata` condicional no Windows, D1), uso, exemplos, limites D14, "estimativa da energia atribuível, não fatura", catálogo parcial/indicativo, tarifa sem tributos/bandeiras, política de tarifa manual/adicional. `docs/arquitetura.md`: contextos DDD e regra de dependência. `docs/fontes-de-dados.md`: URLs, resource ids, schemas reais, encodings, `Content-Type` observado, proveniência e riscos 1, 2, 5 e 6. `docs/telemetria.md`: escopos, política de cobertura, RAPL (permissão, zonas somadas, wrap/reset, `P_MAX_W`, `enabled`), WMI (v1 sempre `component`, D15, nunca testado em Windows, propriedade de leitura e `BaseUnits` OPEN, riscos 3 e 4). `docs/extensoes.md`: porta Proxmox só documentada; wallplug/IPMI/smartplug só como providers futuros. `docs/checklist-instalacao.md`: passos de A50 e comandos de verificação. `docs/matriz-requisitos-testes.md`: A1–A53 mapeados ao arquivo e à função `test_aNN_*` real das etapas 1–17 (cada ID em exatamente um teste); marcar A51–A53 como live/não executados na fase de planejamento. Não modificar `requirements/research.md` nem qualquer evidência.
- **Test**: sem testes novos; `grep` confirma que cada ID A1–A53 da matriz aponta para exatamente uma função `test_aNN_` existente.
- **Verify**: `python -m pytest`; `python -m compileall src tests`; `grep -c "^| A" docs/matriz-requisitos-testes.md` igual a 53.
