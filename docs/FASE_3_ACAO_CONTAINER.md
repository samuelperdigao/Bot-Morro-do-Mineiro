# Fase 3 — Painel Container inicial de Ação

Data: 17/10/2026

## Escopo

Foi adicionada uma versão experimental em Components V2 do painel inicial de
Ação. A publicação ocorre somente pelo comando administrativo
`/setup_acao_container_teste`, no canal em que ele for executado.

O painel contém apenas a entrada para iniciar a ação. A seleção de tipo, o
modal de configuração, o seletor de missão e o painel de participantes seguem
usando as Views e o `AcaoService` existentes.

## Compatibilidade

- O novo painel usa `LayoutView`, `Container`, `TextDisplay`, `Separator`,
  `ActionRow` e `Button`.
- O botão delega ao callback atual de `AcaoPainelView`, preservando permissões,
  respostas e o fluxo de seleção de tipo.
- O novo ID é `acao_container_test:iniciar`; o ID legado
  `acao_painel:iniciar` continua ativo.
- Os IDs `acao:entrar`, `acao:sair`, `acao:adicionar`, `acao:remover` e
  `acao:encerrar` continuam pertencendo somente ao painel de participantes,
  que não foi convertido.
- Mensagens antigas não são editadas, removidas ou substituídas.

## Rollback

Basta deixar de usar `/setup_acao_container_teste`. Os painéis existentes e
seus fluxos de participantes permanecem disponíveis.
