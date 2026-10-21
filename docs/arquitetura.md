# Arquitetura

DDD leve, sem framework: cinco contextos com domínio puro, casos de uso em `application`,
adaptadores em `infrastructure`, interface em `interface` e uma única composição.

## Contextos (em `src/pc_energy_cost/domain/`)

- `energy_estimation`: estimativa de energia e custo, agenda e fuso, integração de potência com
  cobertura.
- `metering`: modelo de medição (amostras, escopo, disponibilidade) e a porta `MeteringProvider`.
- `tariff_catalog`: registros de tarifa, perfil B1 e seleção por vigência com dedupe.
- `location_supplier`: município, distribuidora e resolução do vínculo.
- `usage_session`: sessões de uso (modelo `Session`, acumuladores, ciclo de vida puro em `lifecycle.py`: recuperação após queda, classificação de lacunas entre relógio de parede e monotônico, sensor obsoleto, resumo de custo `SessionCostSummary`). Só importa `domain` e a biblioteca padrão.
- `shared`: dinheiro, unidades, parsing de decimais e erros estáveis com códigos de saída.

## Regra de dependência

```
interface  ->  application  ->  domain
infrastructure ->  application / domain   (implementa as portas)
composition    ->  todas (único ponto que liga as camadas)
```

- `domain` não importa `sqlite3`, `urllib`, `os`, `subprocess` nem `csv`, e não usa `float`.
- `application` depende só de `domain`; define as portas (`TariffSource`, `Store`, `Clock`, ...). As portas de sessão também vivem em `application/ports.py`: `LiveMeter` (leitura incremental do sensor, com `availability()`, `max_tick_s()`, `energy_basis()` e `tick()`; `energy_basis()` é um acréscimo ao desenho inicial do plano), `SessionLedger`, `SummaryExporter`, `BootIdentity` e `MonotonicClock`.
- `infrastructure` (ANEEL/CKAN, HTTP, cache de arquivo, SQLite, providers de medição) implementa as
  portas e não conhece a CLI.
- `interface/cli` recebe os serviços injetados (`Services`); `composition.py` monta tudo e
  `__main__.py` é a entrada.

A regra é verificada por teste de arquitetura (A47: `tests/architecture/test_layering.py`), que
também checa que o teste não é vacuoso. Dinheiro e energia usam `Decimal` (A8).

## Sessões: ledger separado e CLI

- As sessões ficam em `sessions.sqlite`, um arquivo SQLite separado no mesmo diretório do store (`SqliteSessionLedger` em `infrastructure/persistence/sqlite_sessions.py`, com `user_version` próprio). O `store.sqlite` não é aberto nem alterado por sessões: o modo WAL (com `synchronous=FULL`) vale só para o arquivo do ledger. O ledger é aberto de forma preguiçosa, só pelos subcomandos `sessao`.
- `LiveManualPower` existe em `infrastructure/metering/live_manual.py`, mas a CLI atual usa, para a potência informada, o `_AssumedPowerMeter` privado de `application/track_session.py`; os dois têm a mesma semântica e o primeiro ainda não é usado pela composição.
- Casos de uso novos: `track_session` (laço com relógios, `sleep` e `LiveMeter` injetados), `session_report` (listagem e custo por período) e `export_summary`.
- Comportamento da CLI: `sessao custo` exige `--desde` (`--ate` padrão = agora); `sessao exportar` recebe o id da sessão como argumento posicional e a tarifa é opcional nele; `sessao` com `--permitir-cache-vencido` aceita o catálogo vencido mas hoje não imprime o aviso de catálogo vencido (limitação conhecida); o custo por período assume potência uniforme dentro da sessão.
