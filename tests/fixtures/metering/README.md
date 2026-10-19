# Fixtures de medicao

Todos os arquivos desta pasta sao SINTETICOS (inventados para os testes), nao sao medicoes reais.

- `serie_valida.csv`: serie `timestamp,watts` com offset explicito e timestamps naive (America/Sao_Paulo).
- `serie_gap.csv`: amostras de 5 min separadas por um gap de 55 min (maior que o max_gap default de 5 min).
- `serie_invalida.csv`: cabecalho correto e uma linha com timestamp invalido (linha 3).
- `powercap_fake/`: arvore FAKE no formato do sysfs powercap (baseline RAPL do passo 13); os testes copiam para `tmp_path` para criar variantes.
