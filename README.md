# pc-energy-cost

![pc-energy-cost: PC ligado, energia em kWh, tarifa em R$/kWh e custo estimado (valores de exemplo)](docs/images/capa.svg)

## Propósito e público

Estima, em BRL, o custo da energia atribuível a um PC ligado por uma duração planejada ou medida, e acompanha esse custo ao vivo em sessões de uso.

Serve ao usuário residencial brasileiro avançado ou à pessoa desenvolvedora que quer números reprodutíveis (mesma entrada, mesma saída) e uma indicação clara do que foi medido, do que foi informado e do que ficou sem dados. **É uma estimativa da energia atribuível, não uma fatura.** Veja "Limites e avisos" e "Limitações" abaixo.

Programa de linha de comando em Python (3.11 ou superior), sem agente, sem LLM e sem serviço pago no runtime. A tarifa vem do dado aberto da ANEEL (ou é informada manualmente); a potência é informada, lida de um CSV ou, opcionalmente, medida por telemetria do próprio computador.

## Demonstração

A imagem de capa mostra o fluxo com valores de exemplo (100 W por 10 h, R$ 0,78938 por kWh). O exemplo executável abaixo é determinístico (período por `--inicio`/`--fim`, tarifa manual, sem rede e sem depender do relógio) e foi executado com um banco isolado:

```
pc-energy-cost estimar --potencia 100 --inicio 2026-10-19T08:00 --fim 2026-10-19T18:00 --tarifa-manual-total 0,80 --inclui tributos
```

Campos estáveis da saída:

```
Custo estimado: R$ 0,80
Energia: 1,000 kWh
Duração solicitada: 10 h 00 min 00 s
```

A conta é kWh = W x h / 1000 (100 W por 10 h = 1,000 kWh) e custo = kWh x tarifa total (1,000 x R$ 0,80). O teste de documentação `tests/docs/test_readme_contract.py` executa este comando e confere esses campos.

## Papel e escopo

O programa estima a energia atribuível a um PC e a converte em BRL com uma tarifa. Não calcula fatura, não mede a tomada e não substitui o medidor da distribuidora.

O que NÃO faz: não inclui tributos nem bandeira tarifária na tarifa automática da ANEEL (só na manual, se declarado); não mede potência de tomada (nenhum provider afirma escopo de sistema inteiro); não escreve em nenhum Proxmox, não usa credenciais nem rede para isso e não é uma integração oficial com o Proxmox (há apenas uma exportação de texto, veja a seção própria).

## Decisões técnicas

Três decisões que moldam o código, cada uma com a alternativa descartada e a evidência no repositório.

**(a) `Decimal` com arredondamento HALF_UP só na apresentação, em vez de `float`.** Dinheiro e energia acumulam muitas parcelas pequenas; `float` introduz erro binário que aparece em centavos e quebra a reprodutibilidade (0,1 + 0,2 não é 0,3). Evidência: o teste A8 (`tests/architecture/test_layering.py`) proíbe `float` no domínio e confere que os objetos de valor usam `Decimal`; `tests/unit/test_units_money.py` fixa o arredondamento (A2, A3, A7).

**(b) Núcleo sem I/O, com portas e adaptadores, em vez de um script único.** O domínio e os casos de uso não importam `sqlite3`, rede, `os` nem `subprocess`; só os adaptadores falam com o mundo, e uma única composição os liga. Isso permite testar tudo com fakes e trocar fontes (ANEEL, CSV, RAPL, WMI, SQLite) sem tocar nas regras. Evidência: `tests/architecture/test_layering.py` (A47, verificação por AST das dependências entre camadas), as portas em `src/pc_energy_cost/application/ports.py` e a ligação em `src/pc_energy_cost/composition.py`.

**(c) Sessões geridas pelo aplicativo, em vez de derivadas de logs do SO.** Uma sessão é o tempo em que `sessao acompanhar` está rodando (decisão do usuário); o ciclo de vida e o armazenamento são do próprio programa, e o SO entra no máximo como corroboração opcional (identificador de boot no Linux). Comparação feita sobre o host de desenvolvimento e os arquivos do repositório:

| Critério | Facilidades do SO (`/proc/uptime`, `boot_id`, `last -x`, `journalctl --list-boots`, Event Log) | Ciclo de vida e SQLite do aplicativo |
|---|---|---|
| Portabilidade | Nomes e APIs diferentes por SO; o CI roda Ubuntu e Windows | Mesmo código nos dois (`sqlite3` da biblioteca padrão) |
| Testabilidade | Depende do host; `last` e `journalctl` não são fixáveis em fixture | Portas fake de relógio, monotônico e boot, como em `tests/application/session_fakes.py` |
| Retenção | Por rotação de logs ou configuração do journald | Própria e consultável por SQL |
| O que registra | Boot, desligamento e login, não "uso do computador" | Exatamente o que o aplicativo define como sessão, com o motivo do fim |
| Privilégio | Leitura de logs pode exigir grupo ou privilégio; o repositório proíbe `sudo` | Arquivo do usuário no diretório de dados |
| Tempo com o aplicativo parado | Existe registro | Não existe: o tempo é DESCONHECIDO, nunca zero |

O custo assumido é o da última linha: só há sessão onde `acompanhar` esteve rodando. Evidência: `src/pc_energy_cost/application/track_session.py`, `src/pc_energy_cost/infrastructure/persistence/sqlite_sessions.py` e `tests/infrastructure/test_sqlite_sessions.py`.

A decisão anterior, cobertura explícita com `--max-gap` em vez de interpolar ou zerar, continua valendo e está na próxima seção.

## Tratamento de dados incompletos

Regra geral: ausência de dado nunca vira zero nem é preenchida por extrapolação.

- Série CSV com intervalo maior que `--max-gap` (padrão 5 min): o intervalo é excluído e listado, o resultado fica marcado como `partial_data` e o custo cobre só a parte coberta. Evidência: `src/pc_energy_cost/domain/energy_estimation/integration.py` e `tests/unit/test_integration.py` (A10 a A13).
- Nada coberto: o erro é `insufficient_coverage`; nunca se devolve `R$ 0,00` por falta de dados. Zero watt medido e coberto é `R$ 0,00` válido, e é diferente de não ter cobertura.
- Sensor indisponível (sem permissão, sem medidor, zona desabilitada): erro `unavailable` com saída 6, nunca zero. Em `sessao acompanhar`, só `--potencia` com `--completar-com-potencia` preenche trechos sem leitura, e esse trecho é rotulado "assumido", nunca "medido".
- Sensor obsoleto no meio da sessão: sem leitura válida por mais de 3 intervalos, o custo congela no último valor medido, a tela mostra "sem leitura (obsoleta há ...)" e o tempo sem leitura cresce em "excluído". Nada é extrapolado.
- Catálogo de tarifas vencido: exige `--permitir-cache-vencido` (a idade do cache é exibida). O programa não baixa nada no meio de `sessao acompanhar`.
- Sessões: o tempo em que `acompanhar` não está rodando é DESCONHECIDO, nunca zero e nunca estimado. Se o processo morrer (queda, reinício), a sessão é fechada na próxima execução no último batimento gravado, e o erro do fim é no máximo o intervalo de persistência (`--persistir-a-cada`, padrão 60 s).

Exemplo executável (série sintética do repositório com uma lacuna de 55 minutos):

```
pc-energy-cost estimar --serie-csv tests/fixtures/metering/serie_gap.csv --tarifa-manual-total 0,78938
```

Campos estáveis da saída:

```
Custo estimado: R$ 0,01
Energia: 0,017 kWh
Duração coberta: 0 h 10 min 00 s (cobertura)
Duração excluída: 0 h 55 min 00 s
Dados parciais: o custo cobre apenas a parte coberta.
```

Limitação conhecida: neste comando a série CSV aparece na saída rotulada com escopo "manual (potência informada)"; por isso a linha de escopo foi omitida do trecho acima. Com `--max-gap 1h` o mesmo arquivo é integrado por inteiro.

## Instalação

A partir de um checkout do código-fonte:

```
python -m pip install .
```

Para desenvolvimento (inclui `pytest` e `build`):

```
python -m pip install -e ".[dev]"
```

A partir de um sdist ou wheel gerado localmente:

```
python -m build
python -m pip install dist/pc_energy_cost-0.1.0-py3-none-any.whl
```

O pacote `tzdata` é dependência condicional apenas no Windows (que não traz o banco de fusos do IANA); o `pip` o instala sozinho nessa plataforma. No Linux usa-se o banco de fusos do sistema. Sem dados de fuso o programa falha com o erro `timezone_data_missing`.

Depois de instalado, o comando é `pc-energy-cost` (ou `python -m pc_energy_cost`).

## Uso

Os exemplos abaixo foram executados com um banco isolado (`PC_ENERGY_COST_DB`) e funcionam sem rede. A pasta de dados padrão é a do usuário na plataforma; a variável `PC_ENERGY_COST_DB` indica outro arquivo SQLite (o cache de downloads fica ao lado, com sufixo `.cache`, e o ledger de sessões fica ao lado, em `sessions.sqlite`).

Estimativa com potência e horas informadas e tarifa manual (sem rede):

```
pc-energy-cost estimar --potencia 100 --horas 10 --tarifa-manual-total 0,78938
```

Saída (trecho): `Custo estimado: R$ 0,79` e `Energia: 1,000 kWh`.

Tarifa manual que já inclui tributos e bandeira, com saída JSON (schema versão `"1"`):

```
pc-energy-cost estimar --potencia 100 --horas 10 --tarifa-manual-total 0,80 --inclui tributos --inclui bandeira --json
```

Série CSV `timestamp,watts` (fixtures sintéticas do repositório), integrada por degraus:

```
pc-energy-cost estimar --serie-csv tests/fixtures/metering/serie_valida.csv --tarifa-manual-total 0,78938 --max-gap 5m
```

Período por data e hora (naive = `America/Sao_Paulo`) está na seção "Demonstração". Tarifa automática da ANEEL (exige rede; o primeiro download do catálogo é grande, na casa de 200 MB, e não foi executado ao validar estes exemplos de README; o teste live A51 o exercita):

```
pc-energy-cost atualizar-catalogo
pc-energy-cost estimar --distribuidora 61695227000193 --potencia 100 --horas 10
pc-energy-cost estimar --municipio 3550308 --distribuidora 61695227000193 --potencia 100 --horas 10
```

Opções principais de `estimar`: `--potencia`, `--cenario-potencia-nominal`, `--serie-csv`, `--horas` ou `--inicio`/`--fim`, `--max-gap`, `--trapezio`, `--municipio`, `--distribuidora`, `--tarifa-manual-total`, `--inclui`, `--adicional-kwh`, `--adicional-tipo`, `--projetar-ultima-tarifa`, `--rapl-max-watts`, `--permitir-cache-vencido`, `--json`. Sem `--potencia`, `--cenario-potencia-nominal` ou `--serie-csv`, o programa tenta medir por telemetria (RAPL no Linux, WMI no Windows); veja `docs/telemetria.md`.

### Política de tarifa manual e adicional

- `--tarifa-manual-total` é uma tarifa all-in em R$/kWh; `--inclui` declara o que ela contém (`tributos`, `bandeira`, ...). Sem `--inclui` a saída mostra `nao-declarado`.
- `--adicional-kwh` com `--adicional-tipo` soma um valor por kWh (por exemplo, bandeira) à tarifa. Declarar a mesma inclusão na tarifa manual e no adicional é `double_inclusion`; adicional sobre tarifa manual sem inclusões declaradas é `inclusion_undeclared`.
- Tarifa manual `0` é aceita com o aviso `zero_rate`; negativa ou fora dos limites é `invalid_input`.

## Sessões e custo em tempo real

O subcomando `sessao` acompanha o custo ao vivo e guarda um registro de cada sessão. Uma sessão é o tempo em que `sessao acompanhar` está rodando; os períodos em que ele está parado são desconhecidos (decisão do usuário), e não há serviço do SO neste ciclo.

```
pc-energy-cost sessao acompanhar --potencia 100 --tarifa-manual-total 0,80 --intervalo 5
pc-energy-cost sessao listar
pc-energy-cost sessao custo --desde 2026-10-01 --tarifa-manual-total 0,80
pc-energy-cost sessao exportar 1 --tarifa-manual-total 0,80
```

- `acompanhar` lê o sensor (RAPL no Linux, WMI no Windows) ou usa `--potencia`; Ctrl+C encerra a sessão com o motivo `user_stop`. Em terminal (TTY) reescreve uma linha; fora dele, ou com `--json`, imprime uma linha completa por atualização (com `--json`, um documento JSON por linha, no schema versão `"1"`). A tarifa vem do catálogo em cache ou da tarifa manual, e o laço nunca faz rede.
- `listar` mostra as sessões (com `--desde`/`--ate` opcionais). `custo` exige `--desde` (`--ate` padrão = agora) e soma o custo estimado das sessões do período, separando a parte medida da assumida. `exportar` recebe o id da sessão como argumento posicional e a tarifa é opcional nele.
- A energia é sempre rotulada: medida (contador de energia ou potência instantânea do sensor) ou assumida (potência informada ou cenário). Os dois totais aparecem separados; a soma só aparece acompanhada das partes. O custo em BRL continua sendo estimativa, nunca fatura.
- O custo por período assume potência uniforme dentro de cada sessão, e a divisão por vigência de tarifa reaproveita a mesma lógica de `estimar`.
- Se o relógio de parede e o monotônico se descolam entre dois tiques, o intervalo é tratado conforme a diferença: salto sem correspondente vira `clock_discontinuity` (excluído), e o intervalo em que o delta da parede excede o delta monotônico por mais que a tolerância (com o monotônico dentro da tolerância) é classificado como suspensão provável, que fecha a sessão e abre outra no retorno. O programa não afirma como os relógios do sistema se comportam durante a suspensão em nenhum sistema operacional, e isso não foi verificado (inclusive no Windows).

Padrões desta versão (NÃO são decisões do usuário e podem mudar): `--completar-com-potencia` precisa ser explícito para preencher trechos sem leitura; suspensão divide a sessão; `session_already_open` e `session_not_found` saem com código 2; atualização a cada 5 s e persistência a cada 60 s, ambas configuráveis em [1 s, 1 h] (`--intervalo` e `--persistir-a-cada`, este não menor que o primeiro); sensor obsoleto após 3 intervalos; uma sessão aberta é considerada viva se o último batimento tem menos de 2 vezes o intervalo de persistência (logo após uma queda, um novo `acompanhar` pode ser recusado por até esse tempo). Esses valores são provisórios e não foram medidos.

Armazenamento: as sessões ficam em um arquivo SQLite separado, `sessions.sqlite`, no mesmo diretório do banco de dados; o `store.sqlite` (tarifas, vínculos, preferências) não é aberto nem alterado por `sessao`. Só o ledger usa o modo WAL com `synchronous=FULL`; segundo a documentação do SQLite (https://www.sqlite.org/pragma.html), nesse modo uma transação confirmada é durável mesmo em perda de energia. O programa não faz nenhuma afirmação sobre o que o hardware ou o SO fazem com o disco. Como a gravação de sessões não é transacional junto com o `store.sqlite`, uma falha em um não desfaz o outro (o laço só lê a tarifa).

Limitação conhecida: `sessao` com `--permitir-cache-vencido` aceita o catálogo vencido, mas hoje não imprime o aviso de catálogo vencido que `estimar` imprime.

Exemplos de erro de estado, que saem com código 2 (o segundo vale em banco vazio):

```
pc-energy-cost sessao exportar 99
```

```
Erro [session_not_found]: sessão 99 não encontrada
```

Em um banco vazio, `pc-energy-cost sessao listar` imprime `Nenhuma sessão registrada.` e sai com 0.

## Exportação Proxmox-compatível (texto)

`sessao exportar <id>` gera um texto simples em pt-BR (sem HTML) com período, escopo, energia medida e assumida, tempo coberto e excluído, custo estimado, tarifa por vigência e os rótulos "estimativa, não fatura" e "dados parciais" quando houver. O usuário cola esse texto onde quiser, por exemplo no campo de notas de uma VM.

É uma exportação de texto Proxmox-compatível, NÃO uma integração oficial: não há escritor de API, credenciais, token nem chamada de rede. A API oficial documenta o campo `description` da VM com tamanho máximo 8192; a documentação consultada não informa se a unidade é caracteres ou bytes, por isso o exportador respeita os dois limites (8192 caracteres e 8192 bytes UTF-8) e, se exceder, corta por linhas inteiras e informa que truncou. Também não foi verificado se a interface do Proxmox renderiza Markdown; por isso o texto não depende disso. Um adaptador de API é trabalho futuro e está descrito em `docs/extensoes.md`.

## Limites e avisos

- Resultado = estimativa da energia atribuível ao PC. Não é a fatura residencial.
- A tarifa automática é a B1 residencial convencional (Tarifa de Aplicação, TUSD + TE por MWh) da distribuidora e **não inclui tributos nem bandeiras tarifárias**.
- O catálogo de distribuidoras e municípios é parcial e indicativo: o vínculo município e distribuidora vem de indicadores de qualidade da ANEEL, não de cadastro de concessão, e pode haver mais de uma distribuidora por município (a capital de São Paulo é ambígua). Nesse caso o programa devolve `supplier_ambiguous` (saída 3) com as candidatas, em vez de adivinhar; use `--distribuidora` com o CNPJ.
- Os dados reais da ANEEL têm créditos negativos de TUSD/TE em outras classes de tarifa; eles são guardados como vieram, sem interpretação, e não afetam o perfil B1 residencial convencional.
- Limites de entrada (D14): potência até 100000 W com até 3 casas decimais; horas até 87600 com até 4 casas; tarifa manual até 100 R$/kWh com até 6 casas; `--max-gap` de 1 s a 24 h; `--rapl-max-watts` de 1 a 10000. Textos numéricos têm no máximo 32 caracteres. Valores `nan`, `inf`, negativos ou ambíguos (`1,234.5`, `1.234`) são rejeitados.
- Arredondamento HALF_UP só na apresentação; os cálculos internos usam `Decimal`.
- Telemetria: RAPL mede só o pacote da CPU (escopo `cpu_package`); WMI é sempre `component`. Nunca se apresenta medição de tomada. Os limites de amostragem do RAPL são provisórios e não medidos.

## Códigos de saída

| Código | Significado | Exemplos de erro |
|---|---|---|
| 0 | sucesso | |
| 2 | entrada inválida ou estado inválido | `invalid_input`, `ambiguous_decimal`, `double_inclusion`, `inclusion_undeclared`, `timezone_data_missing`, `csv_*`, `insufficient_coverage` (série CSV), `session_already_open`, `session_not_found` |
| 3 | escolha ou resultado ambíguo/sem suporte | `supplier_ambiguous`, `unsupported`, `tariff_ambiguous` |
| 4 | dados de tarifa/catálogo | `tariff_not_found`, `tariff_not_in_effect`, `schema_mismatch`, `unexpected_html`, `download_incomplete`, `cache_corrupted` |
| 5 | sem rede | `network_unavailable` |
| 6 | indisponível | `unavailable`, `insufficient_coverage` (telemetria por contador) |

Com `--json`, erros saem como documento JSON em stdout com `error.code`.

## Verificação e testes

```
python -m pytest                 # suíte padrão
python -m pytest -m install      # sdist -> wheel -> venv limpo (usa a rede)
python -m pytest -m live         # ANEEL e RAPL reais (rede/hardware)
python -m pytest -m live_windows # só em Windows real
```

Evidência reproduzível (medida em 2026-10-21 neste checkout, no host de desenvolvimento em Linux). Os comandos e a saída real:

```
python -m pytest --collect-only -q | tail -2
602/606 tests collected (4 deselected) in 0.29s
python -m pytest -q | tail -1
602 passed, 4 deselected in 31.00s
```

Os 53 cenários planejados do primeiro ciclo (A1 a A53) e os da série S (S1 a S14) e R1 estão mapeados em `docs/matriz-requisitos-testes.md`; eles não equivalem a esse número de testes aprovados, porque a suíte tem parametrizações e testes de apoio. O teste R1 (`tests/docs/test_readme_contract.py`) confere que os números acima coincidem com a coleta do pytest, que os exemplos deste README reproduzem os campos citados e que os caminhos citados existem.

Situação dos testes que dependem de ambiente:

- A51 (ANEEL real) passou em 2026-10-19 contra dados reais, com a REH vigente naquele dia (observação pontual: o teste falha de propósito se a REH mudar).
- A52 (RAPL real) foi pulado no host de desenvolvimento com o motivo `zone_disabled`; isso não se generaliza para outros hosts.
- A53 e o provider WMI (inclusive o medidor ao vivo usado por `sessao acompanhar`) nunca foram testados em Windows real (somente fakes).
- A CI (`.github/workflows/ci.yml`) roda a suíte padrão em Ubuntu e Windows; o Windows nunca foi executado localmente por este projeto, então falhas específicas dessa plataforma ainda podem aparecer na primeira execução.

## Limitações

- É estimativa de energia atribuível, não fatura; a tarifa automática não inclui tributos nem bandeira.
- RAPL mede só o pacote da CPU e WMI só um componente; não há medição de tomada. Os limites de amostragem são provisórios e não medidos.
- O provider WMI e o medidor ao vivo WMI nunca rodaram em Windows real, e o teste live de RAPL foi pulado no host de desenvolvimento.
- Sessões só existem enquanto `sessao acompanhar` roda; o resto do tempo é desconhecido. Os padrões de intervalo, persistência e vivacidade são provisórios.
- A potência informada em `sessao acompanhar` vale para a sessão inteira; o custo por período assume potência uniforme dentro de cada sessão.
- `estimar --serie-csv` rotula a série com escopo "manual"; `sessao --permitir-cache-vencido` não imprime o aviso de catálogo vencido.
- A exportação Proxmox é só texto; não existe escrita via API, e a unidade do limite de 8192 e a renderização de Markdown não foram verificadas.
- O catálogo de vínculo município e distribuidora é parcial e indicativo.

## Documentação

[docs/architecture.md](docs/architecture.md) (fluxo da entrada até a saída, com diagrama), [docs/arquitetura.md](docs/arquitetura.md), [docs/fontes-de-dados.md](docs/fontes-de-dados.md), [docs/telemetria.md](docs/telemetria.md), [docs/extensoes.md](docs/extensoes.md), [docs/checklist-instalacao.md](docs/checklist-instalacao.md) e [docs/matriz-requisitos-testes.md](docs/matriz-requisitos-testes.md).

## Licença

MIT (ver `LICENSE`). Copyright (c) 2026 Fet0b.
