# Relatório da Fase 2 — estado persistente e recuperação

## Objetivo

Eliminar a dependência de memória para decisões de Set e garantir que
participantes de Ação continuem disponíveis depois de um reinício.

## Arquivos alterados

- `services/db_schema.py`
- `services/db_service.py`
- `cogs/set_views.py`
- `cogs/acao.py`
- `main.py`
- `tests/test_persistent_state.py`

## Mudanças

- Adicionada a tabela aditiva `set_requests`, com guild, solicitante, dados do
  Set, status, canal/mensagem de aprovação, responsável, criação e conclusão.
- O Set grava a solicitação antes de publicar o painel e associa a mensagem
  depois do envio.
- A decisão usa claim atômico (`pending` → `processing`) e conclusão atômica;
  segunda aprovação/recusa é respondida de forma controlada.
- Solicitações em processamento durante um reinício voltam para `pending`;
  nenhum registro é apagado.
- Views de Set pendentes são registradas com `message_id` na inicialização.
- Painéis de aprovação antigos, sem registro persistido, continuam reconhecidos
  pelo `custom_id` e respondem que não podem ser recuperados com segurança.
- Ação continua usando a tabela `acoes`/`acao_participantes`; a finalização
  passou a ser compare-and-set para bloquear duas finalizações concorrentes.

## Compatibilidade preservada

- `set_panel:fazer_set`, `approval:aprovar`, `approval:reprovar` e todos os
  `acao:*` existentes foram mantidos.
- Os comandos slash e os painéis antigos não foram removidos ou editados em
  massa.
- O fallback por nome/ID de cargos do Set permanece intacto.

## Validação

- `python -m pytest tests/ -q`: **216 passed**, 1 warning, 12 subtests.
- `python -m compileall -q main.py core cogs services tests`: aprovado.
- Imports críticos: aprovado.
- Carga local das 31 extensões: aprovada.
- Comandos registrados localmente: 51, todos únicos.
- Inicialização e recuperação das views persistentes: aprovada com SQLite
  temporário.

## Migrations

Nenhuma migração destrutiva foi criada. `set_requests` é criada com
`CREATE TABLE IF NOT EXISTS` e índices idempotentes; a infraestrutura formal de
migrações versionadas ficará na Fase 3.

## Riscos restantes

- Painéis antigos de aprovação publicados antes da persistência não contêm
  dados suficientes para aprovação automática; eles recebem resposta segura e
  não são apagados.
- Ainda é necessário validar no Discord uma mensagem real com `message_id` e
  testar permissões/canais sem tocar produção.
- A confirmação de qual painel de Set é o canônico continua pendente.

## Commit

Será registrado em commit separado após a validação final desta fase.

Não houve deploy, merge na `main` ou alteração em produção.
