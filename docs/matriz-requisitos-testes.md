# Matriz requisitos-testes

Cada cenário planejado A1 a A53 aponta para exatamente uma função `test_aNN_*` existente. Os 53
cenários planejados NÃO são 53 testes aprovados: a suíte tem mais casos (parametrizações e testes
sem identificador A). Os números reais constam no README. Outros testes de apoio (por exemplo,
`test_layering_check_is_not_vacuous_*` e `test_metering_unavailable_providers_*`) não levam
identificador A porque cada identificador aparece em uma só função.

Marcadores: `live` (rede ou hardware reais), `live_windows` (Windows real) e `install` (cria
ambiente isolado e usa a rede) ficam fora de `python -m pytest`; use `-m live`, `-m live_windows`
ou `-m install`.

| ID | Requisito | Arquivo | Função | Execução |
|---|---|---|---|---|
| A1 | kWh = W x h / 1000 | `tests/unit/test_units_money.py` | `test_a01_100w_10h_is_1_kwh` | suíte padrão |
| A2 | Custo e arredondamento de exibição (interno preservado) | `tests/unit/test_units_money.py` | `test_a02_one_kwh_times_rate_displays_rounded_keeps_internal` | suíte padrão |
| A3 | Arredondamento HALF_UP | `tests/unit/test_units_money.py` | `test_a03_round_half_up_not_bankers` | suíte padrão |
| A4 | Zero físico manual é R$ 0,00 válido | `tests/unit/test_estimate.py` | `test_a04_zero_physical_is_valid_money_zero` | suíte padrão |
| A5 | Entradas inválidas e limites D14 | `tests/unit/test_parsing.py` | `test_a05_invalid_inputs_have_stable_code` | suíte padrão |
| A6 | Decimal pt-BR e ambiguidade | `tests/unit/test_parsing.py` | `test_a06_decimal_formats` | suíte padrão |
| A7 | Formato de moeda e JSON em string | `tests/unit/test_units_money.py` | `test_a07_brl_format_and_json_string` | suíte padrão |
| A8 | Sem float no domínio; Decimal nos VOs | `tests/architecture/test_layering.py` | `test_a08_no_float_calls_or_annotations_in_domain_and_value_objects_use_decimal` | suíte padrão |
| A9 | Agenda: adjacência válida, sobreposição rejeitada | `tests/unit/test_schedule.py` | `test_a09_schedule_adjacent_valid_and_overlap_rejected` | suíte padrão |
| A10 | Integração CSV com --max-gap explícito | `tests/unit/test_integration.py` | `test_a10_integracao_csv_com_max_gap_explicito` | suíte padrão |
| A11 | Default de 5 min não cobre amostras de 1 h | `tests/unit/test_integration.py` | `test_a11_default_5min_nao_cobre_amostras_de_1h` | suíte padrão |
| A12 | Cobertura parcial | `tests/unit/test_integration.py` | `test_a12_cobertura_parcial` | suíte padrão |
| A13 | Zero coberto vs sem cobertura | `tests/unit/test_integration.py` | `test_a13_zero_coberto_vs_sem_cobertura` | suíte padrão |
| A14 | Duplicata idêntica vs conflitante | `tests/unit/test_integration.py` | `test_a14_duplicata` | suíte padrão |
| A15 | Série de energia rejeitada pelo cabeçalho | `tests/infrastructure/test_metering_manual_csv.py` | `test_a15_energy_series_rejected_by_header` | suíte padrão |
| A16 | Seleção B1 real (fixture ELETROPAULO) | `tests/unit/test_tariff_selection.py` | `test_a16_real_b1_selection` | suíte padrão |
| A17 | Dedupe vs ambiguidade de tarifa | `tests/unit/test_tariff_selection.py` | `test_a17_dedupe_vs_ambiguity` | suíte padrão |
| A18 | Linhas em kW ignoradas | `tests/unit/test_tariff_selection.py` | `test_a18_kw_rows_ignored` | suíte padrão |
| A19 | Fora de vigência e projeção da última tarifa | `tests/application/test_estimate_cost.py` | `test_a19_out_of_effect_and_projection` | suíte padrão |
| A20 | Divisão por vigências (registros reais) | `tests/unit/test_estimate.py` | `test_a20_split_by_vigencia_real_records` | suíte padrão |
| A21 | Schema guard (HTML e coluna renomeada) | `tests/infrastructure/test_fetcher_cache.py` | `test_a21_html_and_schema_mismatch_keep_previous_cache` | suíte padrão |
| A22 | Cache atômico: download cortado | `tests/infrastructure/test_fetcher_cache.py` | `test_a22_connection_cut_discards_part_and_keeps_cache` | suíte padrão |
| A23 | Offline com cache de 30 h | `tests/application/test_refresh_catalog.py` | `test_a23_offline_with_30h_cache_needs_flag_and_reports_stale_age` | suíte padrão |
| A24 | Mapeamento da capital ambíguo | `tests/unit/test_supplier_resolver.py` | `test_a24_mapeamento_capital_ambiguo` | suíte padrão |
| A25 | Sucessão histórica de agentes | `tests/unit/test_supplier_resolver.py` | `test_a25_sucessao_historica` | suíte padrão |
| A26 | Município com agente único | `tests/unit/test_supplier_resolver.py` | `test_a26_municipio_agente_unico` | suíte padrão |
| A27 | Cobertura ausente (Unsupported) | `tests/unit/test_supplier_resolver.py` | `test_a27_cobertura_ausente` | suíte padrão |
| A28 | Persistência da escolha do usuário separada da oficial | `tests/infrastructure/test_sqlite_store.py` | `test_a28_user_choice_is_persisted_separately_from_official` | suíte padrão |
| A29 | Tarifa manual all-in com inclusões declaradas | `tests/application/test_estimate_cost.py` | `test_a29_manual_all_in_with_declared_inclusions` | suíte padrão |
| A30 | Dupla inclusão | `tests/application/test_estimate_cost.py` | `test_a30_double_inclusion` | suíte padrão |
| A31 | Inclusão não declarada | `tests/application/test_estimate_cost.py` | `test_a31_inclusion_undeclared` | suíte padrão |
| A32 | Tarifa ANEEL + adicional | `tests/application/test_estimate_cost.py` | `test_a32_aneel_plus_additional` | suíte padrão |
| A33 | Tarifa manual zero, negativa e limites | `tests/application/test_estimate_cost.py` | `test_a33_manual_rate_zero_negative_and_limits` | suíte padrão |
| A34 | Contrato comum dos providers de Metering | `tests/contract/test_metering_provider_contract.py` | `test_a34_available_providers_share_contract` | suíte padrão |
| A35 | RAPL: delta simples | `tests/infrastructure/test_metering_rapl.py` | `test_a35_simple_delta` | suíte padrão |
| A36 | RAPL: wrap único | `tests/infrastructure/test_metering_rapl.py` | `test_a36_single_wrap` | suíte padrão |
| A37 | RAPL: wraps indeterminados | `tests/infrastructure/test_metering_rapl.py` | `test_a37_indeterminate_wrap` | suíte padrão |
| A38 | RAPL: reset implausível | `tests/infrastructure/test_metering_rapl.py` | `test_a38_implausible_reset` | suíte padrão |
| A39 | RAPL: salto de relógio | `tests/infrastructure/test_metering_rapl.py` | `test_a39_clock_discontinuity` | suíte padrão |
| A40 | RAPL: zonas (só package somado) | `tests/infrastructure/test_metering_rapl.py` | `test_a40_zones` | suíte padrão |
| A41 | RAPL: sem permissão nunca vira zero | `tests/infrastructure/test_metering_rapl.py` | `test_a41_permission_denied_never_zero` | suíte padrão |
| A42 | RAPL: zona desabilitada | `tests/infrastructure/test_metering_rapl.py` | `test_a42_zone_disabled` | suíte padrão |
| A43 | WMI: sem instâncias ou classe ausente | `tests/infrastructure/test_metering_wmi.py` | `test_a43_no_instances_or_missing_class` | suíte padrão |
| A44 | WMI: sempre escopo component | `tests/infrastructure/test_metering_wmi.py` | `test_a44_never_whole_system_always_component` | suíte padrão |
| A45 | WMI: leitura duvidosa | `tests/infrastructure/test_metering_wmi.py` | `test_a45_doubtful_reading` | suíte padrão |
| A46 | WMI: leitura escalada | `tests/infrastructure/test_metering_wmi.py` | `test_a46_scaled_reading` | suíte padrão |
| A47 | Regra de dependência entre camadas | `tests/architecture/test_layering.py` | `test_a47_import_graph_respects_layers` | suíte padrão |
| A48 | CLI estimar pela composição real (texto e JSON v1) | `tests/cli/test_cli_end_to_end.py` | `test_a48_estimar_via_composicao_real_text_and_json` | suíte padrão |
| A49 | Fuso sem dados é erro de domínio | `tests/unit/test_schedule.py` | `test_a49_missing_timezone_data_is_domain_error` | suíte padrão |
| A50 | Instalação sdist -> wheel -> venv limpo | `tests/install/test_install.py` | `test_a50_install_sdist_wheel_clean_venv` | install; excluído da suíte padrão |
| A51 | Live ANEEL (rede real) | `tests/live/test_live_aneel.py` | `test_a51_live_aneel_eletropaulo_b1` | live; excluído da suíte padrão |
| A52 | Live RAPL (hardware com permissão) | `tests/live/test_live_linux_rapl.py` | `test_a52_live_linux_rapl_delta` | live; excluído da suíte padrão |
| A53 | Live Windows WMI (Windows real) | `tests/live/test_live_windows_wmi.py` | `test_a53_live_windows_wmi_meter` | live_windows; excluído da suíte padrão |

## Observações honestas sobre A50 a A53

- A51 passou em 2026-10-19, contra dados reais, com a REH vigente naquele momento (observação
  pontual; o teste falha de propósito se o dataset trouxer outra REH, para atualizar a fixture).
- A52 foi pulado (`skip`) no host de desenvolvimento com o motivo `zone_disabled`. Isso vale só
  para aquele host; em outros hosts o resultado pode ser diferente.
- A53 nunca foi executado em Windows real. Os testes do provider WMI (A43 a A46) usam apenas
  saídas fake e não contam como live.
