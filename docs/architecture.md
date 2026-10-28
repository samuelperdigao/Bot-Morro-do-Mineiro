# Arquitetura atual

## Visão geral

O bot é um processo Python baseado em `discord.py`. `main.py` cria o bot,
configura intents, inicializa o banco, registra views persistentes, carrega as
extensões de `core/extensions.py` e sincroniza comandos globais.

No evento `on_ready`, o bot sincroniza as permissões das pastas de membros
quando a categoria está configurada. Nessa sincronização, todos os cargos cujo
nome contém `gerente` recebem `view_channel`, `send_messages` e
`read_message_history` nas pastas; cargos de operação de tickets continuam
seguindo sua regra própria. Depois disso, o bot remove comandos por guild para
manter somente os comandos globais ativos.

O cog `cogs.membros` reconcilia os vínculos de pastas no startup: libera pastas
de membros vinculadas a contas que já possuem cargo de gerente e retoma
atribuições pendentes de membros rebaixados. Ao receber o último cargo de
gerente, a pasta individual é liberada pelo fluxo padrão, que limpa as
mensagens e remove o vínculo. Ao perder o último cargo de gerente e possuir o
cargo configurado de membro, a conta recebe uma pasta livre ou uma nova pasta;
nome e ID de jogo são lidos do apelido no formato `Nome | ID`. Sem ID válido,
a atribuição fica registrada no SQLite e é tentada novamente após correção do
apelido ou reinício. As permissões gerais dos cargos gerente permanecem como
acima. A central de disparo continua usando sua configuração própria mesmo
quando seleciona canais da mesma categoria.

## Estrutura

```text
main.py                 entrada e ciclo de vida do bot
cogs/                   comandos, views e integrações por domínio Discord
core/                   configuração, permissões, logs, datas e regras comuns
services/               serviços de domínio, acesso ao banco e schema
features/               fachadas de domínio em adoção gradual
infrastructure/         inicialização e repositórios de persistência
ui/                     superfícies de compatibilidade e mensagens de UI
config/                 layouts declarativos de painéis
tests/                  testes de domínio, banco, views e caracterização
scripts/                operações externas e manutenção autorizada
assets/                 imagens usadas nos embeds
data/                   dados locais não versionados
logs/                   logs locais não versionados
docs/                   documentação, histórico e checklists
```

Nem todo módulo em `cogs/` é uma extensão. `bau_core.py`, `farm_embeds.py` e
`set_views.py`, por exemplo, são módulos de apoio importados por outros
componentes.

## Extensões ativas

A lista executada no startup é exclusivamente `core/extensions.py` e contém:

`cogs.setup`, `cogs.sistema`, `cogs.membros`, `cogs.apelidos`,
`cogs.setup_set`, `cogs.farm`, `cogs.ausencia`, `cogs.acao`, `cogs.anuncio`,
`cogs.encomenda`, `cogs.paineis`, `cogs.setup_paineis`, `cogs.lideranca`,
`cogs.setup_lideranca`, `cogs.adv`, `cogs.colete`, `cogs.farm_painel`,
`cogs.farm_tickets`, `cogs.farm_relatorio`, `cogs.farm_advertencias`,
`cogs.ranking_painel`, `cogs.parcerias`, `cogs.hierarquia`,
`cogs.acao_painel`, `cogs.radio`, `cogs.bau`, `cogs.mod`,
`cogs.recolhimento`, `cogs.bau_gerentes` e `cogs.disparo`.

`cogs/dashboard.py` permanece no repositório, mas `cogs.dashboard` não está na
tupla ativa. Portanto, `/setup_dashboard` não é registrado em um startup atual.
Essa decisão está registrada em `docs/FASE_7_DASHBOARD_LEGADO.md` e só deve ser
revertida após confirmar o uso de mensagens antigas no servidor.

## Limites entre camadas

- `cogs/` lida com interações Discord e coordena serviços.
- `core/` concentra configuração, permissões, datas, logs e helpers.
- `services/` concentra regras e acesso ao SQLite; `db_schema.py` mantém as
  etapas de schema e migração.
- `features/` e `infrastructure/repositories/` fornecem fachadas e adaptadores
  para a organização gradual de Set e Ação.
- `ui/` expõe superfícies de compatibilidade para views existentes.

Ainda existem imports históricos entre cogs e módulos grandes. A organização
é incremental; não mover arquivos nem criar uma nova camada apenas para
corresponder a um template.

## Persistência e configuração

- Banco principal: `data/farm.db`, configurável por `ARQUIVO_BANCO_FARM`.
- Banco separado do Baú: `bau.db`, usado pelo domínio de Baú.
- Configuração por servidor: tabelas `guild_config` e `system_config`.
- Dados locais auxiliares: JSONs em `data/`, não versionados.
- Segredos e caminhos de operação: `.env` e `oracle.key`, não versionados.
- Logs: arquivos por sistema em `logs/`, não versionados.

O código mantém fallbacks e IDs legados. Eles são parte da compatibilidade atual
e não devem ser removidos sem confirmação e testes específicos.

## Views persistentes

`main.py` chama `register_persistent_views`. O registro inclui o painel de Set,
os painéis Container ativos e um fallback de `ApprovalView`; solicitações
recuperáveis são carregadas do banco com seus `message_id`. Os contratos de
`custom_id` estão caracterizados nos testes e devem ser tratados como API.

## Limite operacional

Código local e produção são domínios separados. Os scripts em `scripts/`
podem atravessar esse limite somente após confirmação específica. O deploy usa
um manifesto de arquivos rastreados, valida a host key SSH e preserva os
arquivos substituídos para rollback. A atualização de token transmite apenas a
variável selecionada para o override `.env.token`; `.env`, bancos e logs não
fazem parte do artefato.

Os contratos de autorização, segredo, rollback e ACL estão em
`docs/operations-security.md`.

## Riscos arquiteturais conhecidos

- `services/db_service.py` e vários cogs são grandes e misturam
  responsabilidades.
- Há código legado mantido para compatibilidade.
- Há IDs fixos e dependência de configuração real do Discord.
- Testes locais não provam sincronização global, permissões reais ou mensagens
  existentes no servidor.
