# Extensões

O v1 não implementa nenhuma destas extensões; elas só indicam onde encaixariam.

- **Proxmox**: apenas uma porta documentada. Nada foi implementado nem testado; um adaptador futuro
  leria a potência de um host e implementaria `MeteringProvider` com o escopo apropriado.
- **Tomada medidora (wallplug), IPMI e tomada inteligente (smartplug)**: possíveis providers
  futuros de `MeteringProvider`. Seriam os únicos candidatos a escopo de sistema inteiro, desde que
  provem a associação com o computador; hoje nenhum provider afirma isso.

Contrato para novos providers: `availability()` e `read()` em
`src/pc_energy_cost/domain/metering/ports.py`, escopo declarado e nunca zero fabricado; a suíte
`tests/contract/test_metering_provider_contract.py` deve passar para o novo provider.
