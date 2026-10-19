# Checklist de instalação (A50)

O teste A50 (`python -m pytest -m install`) automatiza estes passos em diretórios temporários.

1. Gerar sdist e wheel (o sdist é construído primeiro e o wheel a partir dele):
   `python -m build --outdir dist .`
2. Criar um venv limpo e instalar o wheel:
   `python -m venv venv-whl` e instalar `dist/*.whl` com o `pip` desse venv.
3. Em outro venv limpo, instalar o `dist/*.tar.gz` do mesmo modo.
4. Em cada venv, verificar:
   - `pc-energy-cost --help` retorna 0 (no Windows, `Scripts\pc-energy-cost.exe`);
   - `python -m pc_energy_cost --help` retorna 0;
   - `python -I -c "import pc_energy_cost; print(pc_energy_cost.__file__)"` aponta para
     `site-packages`, não para o código-fonte;
   - exemplo offline com banco isolado:
     `PC_ENERGY_COST_DB=<arquivo> pc-energy-cost estimar --potencia 100 --horas 10 --tarifa-manual-total 0,78938 --json`
     retorna 0 e `schema_version` `"1"`.
5. No Windows, o metadado do pacote deve trazer `tzdata` como dependência condicional
   (`Requires-Dist: tzdata; sys_platform == "win32"`); o teste confere o metadado, não a
   instalação em Windows real.

Este checklist nunca foi executado em Windows real.
