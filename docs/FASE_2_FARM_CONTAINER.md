# Fase 2 — Painel Container público de Farm

Data: 17/10/2026

## Escopo

Foi adicionada uma versão experimental em Components V2 do painel público de
Farm. A publicação ocorre somente pelo comando administrativo
`/setup_farm_container_teste`, no canal em que ele for executado.

O painel interno `FarmTicketView` não foi alterado. Nenhum botão público lança
Farm ou dinheiro diretamente: a entrada de membro continua abrindo o ticket
semanal pelo callback atual.

## Compatibilidade

- O novo painel usa `LayoutView`, `Container`, `TextDisplay`, `Separator`,
  `ActionRow` e `Button`.
- Cada botão delega ao callback correspondente de `FarmPainelView`; permissões,
  validações e respostas existentes continuam sendo a fonte de verdade.
- Os novos IDs usam o namespace `farm_container_test:`. Os IDs
  `farm_painel:*`, `farm_ticket:*` e os bloqueadores de lançamento legado foram
  preservados.
- `FarmPainelView`, `LegacyFarmLaunchView` e `FarmTicketView` continuam
  existentes e registrados.
- Mensagens antigas não são editadas, removidas ou substituídas.

## Rollback

Basta deixar de usar `/setup_farm_container_teste`. Os painéis existentes e
seus fluxos de ticket permanecem disponíveis.
