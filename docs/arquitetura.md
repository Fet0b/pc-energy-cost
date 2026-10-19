# Arquitetura

DDD leve, sem framework: quatro contextos com domínio puro, casos de uso em `application`,
adaptadores em `infrastructure`, interface em `interface` e uma única composição.

## Contextos (em `src/pc_energy_cost/domain/`)

- `energy_estimation`: estimativa de energia e custo, agenda e fuso, integração de potência com
  cobertura.
- `metering`: modelo de medição (amostras, escopo, disponibilidade) e a porta `MeteringProvider`.
- `tariff_catalog`: registros de tarifa, perfil B1 e seleção por vigência com dedupe.
- `location_supplier`: município, distribuidora e resolução do vínculo.
- `shared`: dinheiro, unidades, parsing de decimais e erros estáveis com códigos de saída.

## Regra de dependência

```
interface  ->  application  ->  domain
infrastructure ->  application / domain   (implementa as portas)
composition    ->  todas (único ponto que liga as camadas)
```

- `domain` não importa `sqlite3`, `urllib`, `os`, `subprocess` nem `csv`, e não usa `float`.
- `application` depende só de `domain`; define as portas (`TariffSource`, `Store`, `Clock`, ...).
- `infrastructure` (ANEEL/CKAN, HTTP, cache de arquivo, SQLite, providers de medição) implementa as
  portas e não conhece a CLI.
- `interface/cli` recebe os serviços injetados (`Services`); `composition.py` monta tudo e
  `__main__.py` é a entrada.

A regra é verificada por teste de arquitetura (A47: `tests/architecture/test_layering.py`), que
também checa que o teste não é vacuoso. Dinheiro e energia usam `Decimal` (A8).
