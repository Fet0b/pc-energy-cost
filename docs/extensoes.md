# Extensões

Existem duas direções de porta distintas, e não se confundem: a de ENTRADA de telemetria (de onde vem a potência) e a de SAÍDA de resumo (para onde vai o custo).

## Porta de entrada: telemetria (`MeteringProvider`)

- **Tomada medidora (wallplug), IPMI e tomada inteligente (smartplug)**: possíveis providers futuros de `MeteringProvider`. Seriam os únicos candidatos a escopo de sistema inteiro, desde que provem a associação com o computador; hoje nenhum provider afirma isso.
- **Leitura de potência de um host Proxmox**: ideia futura, não implementada nem testada; seria um provider de entrada que implementaria `MeteringProvider` com o escopo apropriado.

Contrato para novos providers: `availability()` e `read()` em `src/pc_energy_cost/domain/metering/ports.py`, escopo declarado e nunca zero fabricado; a suíte `tests/contract/test_metering_provider_contract.py` deve passar para o novo provider. Para leitura ao vivo em sessões existe a porta `LiveMeter` em `src/pc_energy_cost/application/ports.py`, coberta por `tests/contract/test_session_ports_contract.py`.

## Porta de saída: resumo de custo (`SummaryExporter`)

`SummaryExporter` (em `src/pc_energy_cost/application/ports.py`) recebe um `SessionCostSummary` e devolve um `ExportOutcome`. O único adaptador é `ProxmoxCompatibleTextExporter` (`src/pc_energy_cost/infrastructure/export/proxmox_text.py`), que gera texto "Proxmox-compatível (texto)" para o usuário colar; não usa rede nem credenciais e não é uma integração oficial.

Trabalho futuro, NÃO implementado: um adaptador de API que grave a `description` de uma VM. Antes dele é preciso decidir alvo (VM ou nó), privilégio mínimo do token, TLS autoassinado e política de substituição (o conteúdo atual seria sobrescrito; um marcador delimitado e o `digest` evitariam apagar notas alheias). Itens não verificados: unidade do limite de 8192 (caracteres ou bytes), se a interface renderiza Markdown e limites da descrição do nó. O contrato `tests/contract/test_session_ports_contract.py` já parametriza a porta, então um segundo adaptador entraria nele sem tocar o núcleo.
