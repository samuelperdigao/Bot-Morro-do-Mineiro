# Fase 7 — dashboard e código legado

## Objetivo

Reduzir carga de inicialização sem apagar código histórico ou assumir que
mensagens antigas podem ser removidas.

## Evidência encontrada

A busca em código Python encontrou `cogs.dashboard` apenas em
`core/extensions.py`; os demais resultados são documentação, textos de ajuda
ou a própria implementação do dashboard. Não há import ativo de outro cog
para `cogs.dashboard`.

## Mudança realizada

- `cogs.dashboard` foi removido somente da tupla `COG_EXTENSIONS`.
- `cogs/dashboard.py` foi mantido no repositório.
- Nenhuma mensagem Discord foi editada ou apagada.
- Nenhum `custom_id` do dashboard foi alterado.
- Nenhum banco ou JSON foi alterado.

Com isso, `/setup_dashboard` deixa de ser registrado numa nova inicialização
do bot, conforme o diagnóstico de que o dashboard não está em uso. Caso uma
mensagem antiga ainda seja confirmada no servidor, o código permanece
disponível para uma decisão posterior e esta remoção deve ser revertida antes
de reativar o fluxo.

## Validação da fase

- Testes: `227 passed, 1 warning, 12 subtests passed`.
- Sintaxe: `compileall` dos diretórios ativos.
- Extensões carregadas localmente: `30` (dashboard excluído).
- Comandos registrados localmente: `50`, todos únicos.
- Código legado: `cogs/dashboard.py` presente.
- Migrações criadas nesta fase: nenhuma.

## Riscos restantes

- A confirmação de que não existem mensagens ativas depende do servidor; o
  código local só comprovou ausência de dependências Python.
- Documentação histórica ainda menciona o dashboard e não foi apagada.

## Próxima fase recomendada

Somente após confirmar as fases de estabilidade no servidor, avaliar uma
atualização isolada do `discord.py`; não converter embeds nem substituir
painéis críticos neste ciclo.
