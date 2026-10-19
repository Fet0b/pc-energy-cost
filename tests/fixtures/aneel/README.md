# Fixture ANEEL

`tarifas_eletropaulo.csv`: recorte real, copiado byte a byte (cabeçalho de 17 colunas e linhas
selecionadas, sem alteração de valores), do CSV de tarifas homologadas da ANEEL baixado em
2026-10-19 (dataset `tarifas-distribuidoras-energia-eletrica`).

Conteúdo: ELETROPAULO (CNPJ 61695227000193), subgrupo B1, modalidade Convencional, classe
Residencial, subclasses Residencial e Baixa Renda, nas vigências 2025-07-04/2025-12-31,
2026-01-01/2026-07-03 e 2026-07-04/2027-07-03 (inclui duplicatas idênticas, SCEE e Base
Econômica); uma linha real em `kW` (grupo A2) da ELETROPAULO; duas linhas idênticas reais de um
segundo CNPJ (CEMIG-D, 06981180000116). Os terminadores de linha CRLF são os do arquivo original.

`indqual_capital.csv` (cp1252, 5 colunas) e `limite_recorte.csv` (UTF-8, 8 colunas): recortes reais,
linhas copiadas byte a byte (terminadores CRLF originais), baixados em 2026-10-19 dos datasets
`indqual-municipio` e `indicadores-continuidade-coletivos-limite` da ANEEL.

Conteúdo: todas as linhas do IndQual dos municípios 3550308 (São Paulo; 201 conjuntos),
2504009 (Campina Grande; conjunto 6818) e 2304277 (Ererê; conjuntos 83 e 13312, agente único).
No limite, todas as linhas dos conjuntos 6818 (EBO 2000-2010, EPB 2010-2013); para os demais
conjuntos, apenas as linhas do maior `AnoLimiteQualidade` e do ano anterior (recorte reduzido; o
conjunto 12450 não tem nenhuma linha no arquivo original).

`package_show_tarifas.json`, `package_show_indqual.json`, `package_show_decfec.json`: respostas
reais do CKAN (`/api/3/action/package_show`) dos datasets `tarifas-distribuidoras-energia-eletrica`,
`indqual-municipio` e `indicadores-continuidade-coletivos` (DEC/FEC), obtidas em 2026-10-19 e
copiadas byte a byte, sem corte de recursos. Contêm os recursos CSV `fcf2906c-...`, `3f841488-...`
e `fd69e1dd-...`.

`tarifas_negativas.csv`: cabeçalho de 17 colunas e três linhas reais copiadas byte a byte (CRLF
originais) do CSV de tarifas, baixado em 2026-10-19, com valores negativos reais fora do perfil
B1 convencional: `-7,53` (EMS, A3a), `-43,88` (Âmbar Amazonas, A3) e `-,69` (TE, B4 SCEE).
