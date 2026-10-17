# Fase 1 — Painel Container de Set

Data: 17/10/2026

## Escopo

O painel de entrada de Set foi convertido para Components V2. Os comandos
administrativos `/setup_set` e `/setup_painel_set` agora publicam um
`LayoutView` com `Container`; o comando `/setup_set_container_teste` continua
disponível para publicações isoladas de teste.

Os painéis legados `SetPanelView` e `PainelSetView` continuam existentes e não
são editados ou substituídos automaticamente.

## Compatibilidade

- O novo painel usa `discord.ui.LayoutView`, `Container`, `TextDisplay`,
  `Separator`, `ActionRow` e `Button`.
- O botão encaminha para o mesmo `SetModal` usado pelos fluxos existentes.
- O ID de produção é `set_container:pedir`; o ID de teste
  `set_container_test:pedir` permanece registrado. Os IDs
  `set_panel:fazer_set` e `painel_set:pedir` foram preservados.
- A view tem `timeout=None` e ambas as variantes são registradas como
  persistentes.
- Os comandos de Set conservam título, descrição, cor e rodapé; `/setup_set`
  também preserva a data de publicação como timestamp do Discord. Já
  `/setup_painel_set` mantém a logo como `MediaGallery` do Container e continua
  gravando a mensagem publicada na configuração da guild.
- Nenhum serviço, repositório, banco, migration ou permissão foi alterado.

## Validação

- View instanciada e validada como `LayoutView` persistente.
- Componentes esperados, os dois namespaces de `custom_id` e a referência da
  logo anexada cobertos por teste.
- Callback coberto para confirmar a criação do mesmo `SetModal`.
- O comando de teste mantém a permissão `manage_guild` e a verificação de
  configuração já usada por `/setup_set`.

## Mensagens existentes e rollback

Mensagens legadas não são editadas automaticamente e continuam funcionais,
pois suas views permanecem registradas. Para voltar a publicar o visual antigo,
basta restaurar a publicação anterior; nenhum dado de Set é migrado ou apagado.
