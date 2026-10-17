# Relatório da Fase 3 — banco, migrações e configuração

## Objetivo

Dar ao SQLite um histórico de migrações idempotentes e criar uma camada única
de leitura de configurações por guild, sem mover todos os IDs nem alterar
valores atuais.

## Arquivos alterados

- `services/db_schema.py`
- `services/db_service.py`
- `core/settings.py`
- `cogs/membros.py`
- `tests/test_settings_and_migrations.py`
- `docs/INVENTARIO_BOT.md`

## Mudanças

- Criada a tabela `schema_migrations` com versões, nomes e data de aplicação.
- As colunas legadas continuam sendo adicionadas apenas quando ausentes.
- A tabela `set_requests` e seus índices possuem etapa versionada e idempotente.
- O índice de tickets ativos passou a ser criado sem recriar tabela. Se dados
  conflitantes impedirem o índice, a migração registra aviso, preserva os dados
  e permanece disponível para nova tentativa.
- Removida da rotina de migração a estratégia antiga de renomear/recriar/apagar
  `farm_tickets`; nenhuma migração contém `DROP TABLE` ou exclusão geral.
- `db_set_guild_config` agora aceita somente uma whitelist explícita de 41
  campos. Valores atuais e chamadas válidas continuam compatíveis.
- Criada `core/settings.py`, com leitura priorizada de `system_config`,
  `guild_config`, referências de painéis, cargos e fallbacks de IDs legados.
- `cogs/membros.py` passou a consumir a camada central para os dois canais
  globais legados, sem alterar seus valores.
- O inventário foi atualizado com todos os IDs fixos encontrados na busca local.

## Compatibilidade preservada

- Não houve alteração dos comandos slash, permissões, mensagens ou
  `custom_id`.
- O banco de produção não foi aberto para escrita.
- Migrações só adicionam estruturas/colunas/índices e preservam dados
  conflitantes para correção explícita.
- Cogs que ainda leem constantes continuam funcionando; a centralização será
  adotada gradualmente.

## Validação

- `python -m pytest tests/ -q`: **220 passed**, 1 warning, 12 subtests.
- `python -m compileall -q main.py core cogs services tests`: aprovado.
- Imports da camada de settings/schema: aprovados.
- Carga local das 31 extensões: aprovada.
- Comandos registrados localmente: 51, todos únicos.
- Migrações em SQLite temporário: idempotentes; dados de ticket legado
  preservados sem tabela auxiliar.
- Busca por `DROP TABLE` e pela antiga recriação de `farm_tickets`: nenhum
  resultado.

## Migrations criadas

1. `ensure legacy columns`
2. `ensure persistent set requests`
3. `ensure active farm ticket index`

## Riscos restantes

- IDs fixos em outros cogs ainda dependem de constantes locais; a migração
  gradual deve ser feita domínio por domínio.
- A validade dos IDs e a presença real dos painéis precisam de confirmação no
  servidor Discord.
- O índice de tickets ativos não pode ser aplicado automaticamente se a base
  já contiver duplicidades; isso é reportado sem modificar registros.

## Commit

Será registrado em commit separado após a validação final desta fase.

Não houve deploy, merge na `main` ou alteração em produção.
