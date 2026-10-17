# Fase 1 — Painel Container de Set

Data: 17/10/2026

## Escopo

Foi adicionada uma versão experimental em Components V2 para o painel de
entrada de Set. A publicação ocorre somente pelo comando administrativo
`/setup_set_container_teste`, permitindo validação visual em um canal de teste.

Os painéis legados `SetPanelView` e `PainelSetView` continuam existentes e não
são editados ou substituídos automaticamente.

## Compatibilidade

- O novo painel usa `discord.ui.LayoutView`, `Container`, `TextDisplay`,
  `Separator`, `ActionRow` e `Button`.
- O botão encaminha para o mesmo `SetModal` usado pelos fluxos existentes.
- O novo `custom_id` é `set_container_test:pedir`, em namespace exclusivo de
  teste. Os IDs `set_panel:fazer_set` e `painel_set:pedir` foram preservados.
- A nova view tem `timeout=None` e é registrada como persistente.
- Nenhum serviço, repositório, banco, migration, permissão ou comando existente
  foi alterado.
- Mensagens antigas do Discord não são editadas.

## Validação

- View instanciada e validada como `LayoutView` persistente.
- Componentes esperados e `custom_id` do botão cobertos por teste.
- Callback coberto para confirmar a criação do mesmo `SetModal`.
- O comando de teste mantém a permissão `manage_guild` e a verificação de
  configuração já usada por `/setup_set`.

## Rollback

Basta deixar de usar `/setup_set_container_teste`. Os painéis existentes e seus
callbacks permanecem disponíveis.
