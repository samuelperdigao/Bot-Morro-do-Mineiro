# Fase 2 — Painel Container público de Farm

Data: 17/10/2026

## Escopo

O painel público de Farm foi convertido para Components V2. `repost_farm_panel`
e `/setup_farm_painel` passam a publicar o Container de produção; o comando
`/setup_farm_container_teste` continua publicando a variante isolada de teste.

O painel interno `FarmTicketView` não foi alterado. Nenhum botão público lança
Farm ou dinheiro diretamente: a entrada de membro continua abrindo o ticket
semanal pelo callback atual.

## Compatibilidade

- O novo painel usa `LayoutView`, `Container`, `TextDisplay`, `Separator`,
  `ActionRow` e `Button`.
- Cada botão delega ao callback correspondente de `FarmPainelView`; permissões,
  validações e respostas existentes continuam sendo a fonte de verdade.
- Os IDs de produção usam `farm_container:` e os de teste usam
  `farm_container_test:`. Os IDs `farm_painel:*`, `farm_ticket:*` e os
  bloqueadores de lançamento legado foram preservados.
- `FarmPainelView`, `LegacyFarmLaunchView` e `FarmTicketView` continuam
  existentes e registrados; ambas as variantes V2 também são persistentes.
- O ciclo de repostagem de Farm que já existia continua removendo painéis de
  Farm reconhecidos e publica o novo Container na inicialização. O
  reconhecimento agora percorre os componentes aninhados do Container, evitando
  duplicidade no próximo reinício.

## Rollback

Os callbacks e IDs legados permanecem registrados. Restaurar a chamada de
publicação anterior reativa o painel antigo sem alterar tickets, metas ou
lançamentos.
