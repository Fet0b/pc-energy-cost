# Telemetria

A telemetria é opcional e sempre declara o escopo da medição.

## Escopos

- `manual`: potência informada pelo usuário ou série CSV.
- `cpu_package`: RAPL, somente o pacote da CPU (parcial em relação ao PC).
- `component`: um componente medido (WMI no v1).
- Não há suporte a `whole_system_ac` (tomada) em nenhum provider do v1.

## Política de cobertura

A integração (`integration.py`) soma energia só nos intervalos cobertos. Um intervalo entre amostras
maior que `--max-gap` (padrão 5 min, entre 1 s e 24 h) é excluído e listado com razão. Há três
resultados distintos: cobertura completa, parcial (`partial_data: true`, custo só da parte coberta)
e nenhuma (`insufficient_coverage`). Zero coberto (0 W medido) é `R$ 0,00` válido; ausência de
cobertura nunca vira zero. Sem permissão ou sem medidor, o provider devolve `Unavailable` com o
motivo, nunca zero fabricado.

## Linux RAPL

- Lê o sysfs powercap (`/sys/class/powercap`), somente leitura, sem `sudo` e sem alterar
  permissões. Se `energy_uj` for ilegível, o resultado é `Unavailable(permission_denied)`.
- Somente zonas `package-N` de topo são somadas; subzonas e outras (por exemplo, `core`, `psys`)
  são listadas como `component`.
- Contador de energia com wrap: um wrap possível é reconstruído com `max_energy_range_uj`; se o
  intervalo permitir mais de um wrap, é excluído como `indeterminate_wrap`. Reset implausível
  (potência acima de `P_MAX_W`) é excluído como `counter_reset_or_invalid`; salto entre relógio
  monotônico e de parede, como `clock_discontinuity`.
- `P_MAX_W` padrão 1000 W, ajustável com `--rapl-max-watts` (1 a 10000). Janela de medição padrão
  de 10 s. Esses limites são provisórios e não foram medidos.
- Zona com `enabled` = 0: `Unavailable(zone_disabled)` (política conservadora; a semântica de
  `enabled` para leitura de energia não foi verificada).
- Teste live (A52): no host de desenvolvimento foi pulado com o motivo `zone_disabled`. Isso
  descreve aquele host, não todos.

## Windows WMI

- Provider (`Win32_PowerMeter`, namespace `root/CIMV2/power`, via `Get-CimInstance` do PowerShell
  com argumentos fixos, sem shell) **nunca foi executado em Windows real**; só foi testado com
  saídas fake.
- v1: escopo sempre `component` (D15). Não há como provar a associação do medidor ao computador,
  então nunca `whole_system_ac` nem `whole_system_unverified`.
- A propriedade de leitura (`CurrentReading`, tratada como herdada de `CIM_NumericSensor`) e a
  decodificação de `BaseUnits` estão em aberto: o código bruto de `BaseUnits` é guardado com o aviso
  `base_units_not_decoded`. `UnitModifier` é a escala usada.
- Casos tratados como indisponíveis: sem instâncias ou classe ausente
  (`no_power_meter_provider`), leitura nula (`reading_property_unverified`), sem `UnitModifier`
  (`unit_unknown`), `SupportCapabilities` 8 ou 256 (`only_when_discharging`) e leitura negativa
  (`invalid_reading`).

## Sessões (leitura ao vivo)

- `sessao acompanhar` lê o sensor por tiques (porta `LiveMeter`, memória O(1): só a leitura anterior). O sensor é lido em passos iguais que dividem `--intervalo` e nunca passam do `max_tick_s` do medidor (por exemplo, `--intervalo 7` com `max_tick_s` 5 lê a cada 3,5 s); a tela é renderizada a cada `--intervalo`. Sem isso, um intervalo longo com RAPL só produziria `indeterminate_wrap`.
- Cada medidor declara a base da energia: `measured_counter` (RAPL, diferença de contador, escopo `cpu_package`), `measured_power` (WMI, potência instantânea integrada por degraus entre tiques, escopo `component`), `user_power` ou `scenario` (potência informada, rotulada como assumida). A energia medida e a assumida são acumuladas separadamente.
- Sensor obsoleto: sem leitura válida por mais de 3 intervalos (padrão provisório), o custo congela, o tempo sem leitura é contado como tempo excluído (`excluded_s`) e nada é extrapolado nem preenchido com zero. Só `--potencia` com `--completar-com-potencia` completa o trecho, rotulado "assumido".
- Medidor WMI ao vivo: `max_tick_s` = 10 s, derivado do timeout do subprocess do PowerShell. Esse valor NÃO foi medido, e o medidor nunca rodou em Windows real. Um intervalo maior que o teto somado ao timeout é excluído como lacuna, não integrado.
- Tempo em que `acompanhar` não roda é desconhecido, não zero. Esta página não afirma como o relógio monotônico se comporta durante a suspensão em nenhum sistema operacional.

## Riscos

3. `Win32_PowerMeter`: documentação legada; hardware real e Windows 10/11 modernos não testados;
   o campo de leitura exato e a classe de associação ao `Win32_ComputerSystem` dependem de
   verificação e hardware.
4. RAPL: a leitura real de `energy_uj` não foi validada; `enabled`, `P_MAX_W` e limites de `dt` são
   provisórios.
