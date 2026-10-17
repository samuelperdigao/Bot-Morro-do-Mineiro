# Fase 3 — Painel Container inicial de Ação

Data: 17/10/2026

## Escopo

O painel inicial de Ação foi convertido para Components V2. O comando
`/setup_acao_painel` publica o Container de produção; o comando
`/setup_acao_container_teste` segue disponível para teste isolado.

O painel contém apenas a entrada para iniciar a ação. A seleção de tipo, o
modal de configuração, o seletor de missão e o painel de participantes seguem
usando as Views e o `AcaoService` existentes.

## Compatibilidade

- O novo painel usa `LayoutView`, `Container`, `TextDisplay`, `Separator`,
  `ActionRow` e `Button`.
- O botão delega ao callback atual de `AcaoPainelView`, preservando permissões,
  respostas e o fluxo de seleção de tipo.
- O ID de produção é `acao_container:iniciar`; o ID de teste
  `acao_container_test:iniciar` e o ID legado `acao_painel:iniciar` continuam
  ativos e registrados.
- Os IDs `acao:entrar`, `acao:sair`, `acao:adicionar`, `acao:remover` e
  `acao:encerrar` continuam pertencendo somente ao painel de participantes,
  que não foi convertido.
- Mensagens antigas não são editadas nem removidas; continuam interativas pelo
  registro da view legada.

## Rollback

Os callbacks legados e o fluxo de participantes permanecem disponíveis.
Restaurar a chamada de publicação anterior reativa o visual antigo sem alterar
as ações registradas.
