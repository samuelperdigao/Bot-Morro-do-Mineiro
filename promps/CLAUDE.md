# FARMBOT — ANÁLISE COMPLETA DO CÓDIGO
Gerado em: 2026-04-21 (atualizado após V2 + melhorias 2026-05-11 + 2026-05-12)

---

## 1. VISÃO GERAL DO PROJETO

Bot Discord multi-servidor para comunidade de GTA RP "Morro do Mineiro".

**Tecnologias:**
- Python + discord.py 2.3.2
- SQLite (WAL mode) — banco: `farm.db`
- Deploy: Oracle Cloud via systemd + SSH/SCP

**Módulos principais:**
| Módulo | Arquivo | Status |
|--------|---------|--------|
| Set (aprovação de membros) | `main.py` + `cogs/set_views.py` | Ativo |
| Farm (cotas semanais, slash) | `cogs/farm.py` | Ativo |
| Farm Painel (painel fixo) | `cogs/farm_painel.py` | Ativo |
| Ausências | `cogs/ausencia.py` | Ativo |
| Ações/Missões (slash) | `cogs/acao.py` | Ativo |
| Ação Painel (painel fixo) | `cogs/acao_painel.py` | Ativo |
| Anúncios | `cogs/anuncio.py` | Ativo |
| Encomendas | `cogs/encomenda.py` | Ativo |
| Hierarquia de Cargos | `cogs/hierarquia.py` | Ativo |
| Configuração (slash) | `cogs/setup.py` | Ativo |
| Dashboard centralizado | `cogs/dashboard.py` | Ativo |
| Painéis customizados | `cogs/paineis.py` | Ativo |
| Setup de painéis | `cogs/setup_paineis.py` | Ativo |
| Adversidade/Advertência | `cogs/adv.py` | Ativo |
| Heroína | `cogs/heroina.py` | Ativo |
| Baú da Gerência (estoque) | `cogs/bau.py` | Ativo |
| Baú — Slots de Gerentes | `cogs/bau_gerentes.py` | Ativo |
| Moderação | `cogs/mod.py` | Ativo |
| Rádio | `cogs/radio.py` | Ativo |
| Recolhimento Semanal | `cogs/recolhimento.py` | Ativo |
| Views do Set (desacoplado) | `cogs/set_views.py` | Ativo |

**Arquivos depreciados (legacy single-server):**
- `bot.py`, `farm.py`, `acao.py`, `ausencia.py` (raiz) — substituídos pelos cogs

**Padrão visual:** dourado `#FFD700`, dark, premium. Footer padrão: "Morro do Mineiro — Sistema de X"

---

## 2. ESTRUTURA DO PROJETO

```
Bot Discord/
├── main.py                  ← Entry point ATUAL (multi-servidor)
├── bot.py                   ← Legacy (DEPRECIADO)
├── farm.py                  ← Legacy (DEPRECIADO)
├── acao.py                  ← Legacy (DEPRECIADO)
├── ausencia.py              ← Legacy (DEPRECIADO)
├── cogs/
│   ├── __init__.py
│   ├── setup.py             ← Comandos de configuração slash
│   ├── farm.py              ← Sistema de farm semanal (slash)
│   ├── farm_painel.py       ← Painel fixo de farm (botões)
│   ├── acao.py              ← Sistema de ações/missões (slash)
│   ├── acao_painel.py       ← Painel fixo de ação (botão)
│   ├── ausencia.py          ← Sistema de ausências
│   ├── anuncio.py           ← Sistema de anúncios
│   ├── encomenda.py         ← Sistema de encomendas
│   ├── hierarquia.py        ← Sistema de hierarquia de cargos
│   ├── dashboard.py         ← Dashboard de configuração centralizado
│   ├── paineis.py           ← Painéis customizados
│   ├── setup_paineis.py     ← Setup de painéis
│   ├── adv.py               ← Sistema de advertências
│   ├── heroina.py           ← Sistema de heroína
│   ├── bau.py               ← Sistema de baú da gerência (estoque)
│   ├── bau_gerentes.py      ← Painel de slots de gerentes do baú
│   ├── mod.py               ← Moderação (/clear)
│   ├── radio.py             ← Sistema de rádio (canal + @everyone)
│   ├── recolhimento.py      ← Recolhimento semanal (dinheiro sujo/farm)
│   └── set_views.py         ← SetModal, ApprovalView, SetPanelView (extraído de main.py)
├── core/
│   ├── config.py            ← Variáveis de ambiente (.env)
│   ├── logger.py            ← Logger com rotação de arquivos
│   ├── permissions.py       ← Funções centralizadas de permissão
│   └── command_config.py    ← Configuração de comandos por guild
├── services/
│   ├── db_service.py        ← Abstração SQLite (700+ linhas)
│   ├── set_service.py       ← Gerenciamento de canais privados
│   ├── log_service.py       ← Função central de log para canais
│   └── paineis_service.py   ← Lógica de painéis customizados
├── config/
│   └── paineis.py           ← Configuração de painéis
├── data/
│   ├── autoroles_config.json
│   └── commands_config.json
├── farm.db                  ← Banco SQLite (+ .db-shm, .db-wal)
├── channel_map.json         ← Legacy (migrado para DB)
├── requirements.txt         ← discord.py==2.3.2, python-dotenv==1.0.0
├── deploy.ps1               ← Script PowerShell → Oracle Cloud
└── oracle.key               ← Chave SSH para deploy
```

---

## 3. TODOS OS COMANDOS E FUNÇÕES

### A) `main.py` — Sistema de Set + Entry Point

**Slash Commands:**
| Comando | Permissão | Descrição |
|---------|-----------|-----------|
| `/setup_set` | manage_guild | Posta painel de solicitação de set no canal atual |
| `/ping` | Nenhuma | Retorna latência do bot |
| `/status` | Nenhuma | Mostra uptime, qtd de servidores, info do banco |

**Classes UI:**
- `SetModal` — Campos: `id_jogo` (numérico, 1-20 chars), `membro_nome` (max 100)
- `SetPanelView` — Botão "📝 Fazer Set" (primary, persistent)
- `ApprovalView` — Botões "✅ Aprovar" e "❌ Reprovar" (persistent, timeout=None)

**Lógica de aprovação (`ApprovalView._processar`):**
1. Verifica permissão do aprovador via `has_approver_permission()`
2. Aplica cargo membro
3. Remove cargo "Pedir Set" se existir
4. **Cria canal privado** (`criar_pasta`) — feito ANTES de definir apelido
5. Define apelido `{nome} | {id_jogo}` — após criar canal (evita duplicação de ID)
6. Posta log verde

**Bug corrigido (V2):** A criação do canal privado ocorria APÓS setar o apelido, fazendo `member.display_name` já conter o `id_jogo`. O `criar_pasta` usava `display_name` e ainda appendava `sufixo=-{id_jogo}`, resultando em duplicação. Ordem invertida resolve.

---

### B) `cogs/setup.py` — Configuração

**Slash Commands:**
| Comando | Permissão | Descrição |
|---------|-----------|-----------|
| `/setup_bot` | manage_guild | Configura sistema de Set |
| `/setup_farm` | manage_guild | Configura Farm (cargos, canais) |
| `/setup_ausencia` | manage_guild | Configura canal de ausências |
| `/setup_encomenda` | administrator | Configura canal de encomendas |
| `/setup_log_saida` | manage_guild | Configura canal de log de saída |
| `/setup_anuncio` | manage_guild | Configura canal + cargos de anúncio |
| `/config_ver` | manage_guild | Mostra configuração atual do servidor |
| `/encomenda` | Nenhuma | Abre modal de registro de encomenda |

---

### C) `cogs/farm.py` — Farm Semanal (Slash)

Produtos: Folha, Ópio, Seringa, Agulha

**Slash Commands:**
| Comando | Permissão | Descrição |
|---------|-----------|-----------|
| `/definir_metas` | Liderança | Abre modal para definir metas da semana |
| `/lancar` | Permitido | Lança itens entregues |
| `/editar` | Liderança | Edita último lançamento |
| `/meu_farm` | Permitido | Mostra progresso pessoal |
| `/ranking` | Qualquer | Top 10 da semana |
| `/aprovar_farm` | Liderança | Aprova entrega do membro |
| `/avisos_farm` | Liderança | Posta painel de avisos |

---

### D) `cogs/farm_painel.py` — Farm Painel Fixo (NOVO V2)

Painel embed fixo no canal configurado via dashboard (sistema "farm").

**Slash Commands:**
| Comando | Permissão | Descrição |
|---------|-----------|-----------|
| `/setup_farm_painel` | manage_guild | Posta o painel no canal configurado |

**Classes UI:**
- `FarmPainelView` — 3 botões persistentes:
  - `farm_painel:lancar` — Abre `LancarFarmModal`
  - `farm_painel:ver` — Resposta ephemeral com progresso
  - `farm_painel:editar` — Abre `EditarFarmModal`
- `LancarFarmModal` — Campo: `quantidade` → salva como `{"Farm": N}` via `db_lancar`
- `EditarFarmModal` — Campos: `novo_valor`, `motivo` → via `db_editar_ultimo_evento`

**Canal:** `system_config(guild_id, "farm")["canal_interacao_id"]`
**Log:** `send_log(bot, guild, "farm", embed)`

---

### E) `cogs/ausencia.py` — Ausências

**Slash Commands:**
| Comando | Permissão | Descrição |
|---------|-----------|-----------|
| `/painel_ausencia` | manage_guild | Posta painel de registro |
| `/ausencias` | Nenhuma | Lista ausências ativas |

**Classes UI:**
- `AusenciaPanelView` — Botão "📋 Registrar Ausência" (persistent)
- `AusenciaModal` — Campos: `dias` (1-7), `motivo`

**Log (V2):** após registrar ausência, envia embed dourado via `send_log(..., "ausencia", ...)`

---

### F) `cogs/acao.py` — Ações/Missões (Slash)

**Slash Commands:**
| Comando | Permissão | Descrição |
|---------|-----------|-----------|
| `/acao` | Nenhuma | Abre modal com data, horário e tipo antes do select de ação |

18 ações definidas em `ACOES` dict.

**Classes UI principais:**
- `AcaoSelectView(horario, tipo, data)` — dropdown de seleção de ação
- `AcaoParticipantesView(acao_key, horario, tipo, data)` — painel de participantes com 5 botões
- `AdicionarMembroPaginadoView` — lista paginada (20/pág) de membros do servidor para adicionar; botões ◀ ▶ quando >20 membros
- `RemoverMembroView` — Select com membros inscritos para remover

**`_build_regras_embed(acao_key, membros_inscritos, horario, tipo, data)`** — param `data` adicionado; quando presentes, exibe no topo do embed: `📅 Data`, `🕐 Hora`, `⚔️ Tipo`.

**Botão "➕ Adicionar membro":** filtra membros não-bots e não inscritos, ordena por nome, exibe dropdown paginado (20/pág) via `AdicionarMembroPaginadoView`. Requer liderança. Depende de `intents.members = True`.

---

### G) `cogs/acao_painel.py` — Ação Painel Fixo

Painel embed fixo no canal configurado via dashboard (sistema "acao").

**Slash Commands:**
| Comando | Permissão | Descrição |
|---------|-----------|-----------|
| `/setup_acao_painel` | manage_guild | Posta o painel no canal configurado |

**Classes UI:**
- `AcaoPainelView` — Botão "⚡ Iniciar Ação" (`acao_painel:iniciar`, persistent)
  - Abre `PreAcaoModal` (coleta data, horário e tipo antes do select de ação)
- `PreAcaoModal` — Modal com **três** campos:
  - `Data da ação` — TextInput livre (ex: "12/05")
  - `Horário da ação` — TextInput livre (ex: "21:00")
  - `Tipo da ação` — TextInput validado: aceita apenas "fuga" ou "tiro"
  - `on_submit`: valida tipo → posta `AcaoSelectView(horario, tipo, data)` no canal configurado
  - Responde ephemeralmente com link para o canal

**Fluxo completo:**
1. Clique em "⚡ Iniciar Ação" → abre `PreAcaoModal`
2. Usuário preenche data, horário e tipo → submit
3. Seletor postado no canal com 📅 Data, 🕐 Horário e ⚔️ Tipo visíveis no embed
4. Usuário escolhe ação → embed de regras exibe os 3 campos no topo

**Canal:** `system_config(guild_id, "acao")["canal_interacao_id"]`
**Log:** `send_log(bot, guild, "acao", embed)` ao iniciar — inclui data, horário e tipo

---

### H) `cogs/anuncio.py` — Anúncios

**Slash Commands:**
| Comando | Permissão | Descrição |
|---------|-----------|-----------|
| `/setup_anuncio` | manage_guild | Configura canal + cargos |
| `/painel_anuncio` | manage_guild | Posta painel no canal atual |

**Log (V2):** após publicar anúncio, envia embed dourado via `send_log(..., "anuncio", ...)`

---

### I) `cogs/encomenda.py` — Encomendas

**Slash Commands:**
| Comando | Permissão | Descrição |
|---------|-----------|-----------|
| `/encomenda` | Nenhuma | Abre modal se canal estiver configurado |

**Log (V2):** após registrar encomenda, envia embed dourado via `send_log(..., "encomenda", ...)`

---

### J) `cogs/hierarquia.py` — Hierarquia de Cargos (NOVO V2)

Painel embed fixo no canal configurado via dashboard (sistema "hierarquia").

**Slash Commands:**
| Comando | Permissão | Descrição |
|---------|-----------|-----------|
| `/setup_hierarquia` | manage_guild | Posta o painel no canal configurado |

**Quem pode usar:** membros com cargo `| 01 Dono`, `| 02`, ou `| 03`

**Hierarquia de cargos (do menor ao maior):**
1. `| Pedir Set`
2. `| Membro`
3. `| Gerente de Recrutamento`
4. `| Gerente de Ação`
5. `| Gerente de Farm`
6. `| Gerente de Produção`
7. `| Gerente Geral`
8. `| 03`
9. `| 02`
10. `| 01 Dono`

**Cargos ignorados (nunca aparecem como opção):**
`| Bots`, `| Programador Dev`, `| Loritta`, `| Rio Bot`, `| Server Booster`, `| Medal`, `| Morro Do Mineiro`, `| Advertência`

**Classes UI:**
- `HierarquiaPainelView` — Botão "👑 Gerenciar Hierarquia" (`hierarquia:gerenciar`, persistent)
- `MembrosSelectView` — `UserSelect` para escolher membro (ephemeral, timeout=120s)
- `CargosSelectView` — `Select` com os 10 cargos da hierarquia (ephemeral, timeout=120s)

**Fluxo:** botão → MembrosSelectView (ephemeral) → CargosSelectView (edit) → aplica cargo, remove anterior, loga

**Log:** embed dourado com executor, membro, cargo anterior, novo cargo, tipo (PROMOÇÃO/REBAIXAMENTO/REATRIBUIÇÃO)

---

### K) `cogs/dashboard.py` — Dashboard Centralizado

**Canal fixo:** `1494692392052461588`

**Sistemas configuráveis (8):**

Página 1/2:
| Chave | Ícone | Nome |
|-------|-------|------|
| `set` | 🎮 | Sistema de Set |
| `farm` | 🌾 | Sistema de Farm |
| `meta` | 🎯 | Sistema de Meta |
| `ausencia` | 🏖️ | Sistema de Ausência |
| `encomenda` | 📦 | Sistema de Encomenda |
| `acao` | ⚡ | Sistema de Ação |
| `anuncio` | 📢 | Sistema de Anúncio |

Página 2/2:
| Chave | Ícone | Nome |
|-------|-------|------|
| `hierarquia` | 👑 | Sistema de Hierarquia |

**Slash Commands:**
| Comando | Permissão | Descrição |
|---------|-----------|-----------|
| `/setup_dashboard` | manage_guild | Posta o dashboard no canal fixo `1494692392052461588` |

**Classes UI:**
- `SystemConfigModal` — Campos: `canal_interacao` (ID), `canal_log` (ID)
- `_DashboardDispatcher` — View persistente com botões ≡ por sistema + navegação ←→

**Persistência:** dashboard_channel_id e dashboard_message_id em `guild_config`. Canais por sistema em `system_config`.

---

### L) `cogs/bau.py` — Baú da Gerência

Sistema de controle de estoque com painel fixo e select menus. Banco próprio: `bau.db`.

**Canais fixos:** `CANAL_BAU_ID = 1474869322387292357`, `CANAL_LOG_ID = 1499589255784173678`

**Categorias de itens:** Itens Gerais, Munições, Attachs, Drogas/Efeitos.

---

### M) `cogs/bau_gerentes.py` — Slots de Gerentes do Baú

Painel de slots de gerentes. Banco: `bau.db`. Canal fixo: `CANAL_GERENTES_ID = 1502107652027715705`. `SLOTS_INICIAIS = 10`.

---

### N) `cogs/mod.py` — Moderação

**Slash Commands:**
| Comando | Permissão | Descrição |
|---------|-----------|-----------|
| `/clear` | manage_messages | Apaga 1–100 mensagens do canal atual |

---

### O) `cogs/radio.py` — Rádio

Painel com botão "📻 Definir Nova Rádio". Canal fixo: `CANAL_RADIO_ID = 1474869321863008296`.

Ao confirmar o modal: renomeia o canal para `radio-{numero}` e envia @everyone com o novo número.

**Slash Commands:**
| Comando | Permissão | Descrição |
|---------|-----------|-----------|
| `/setup_radio_painel` | manage_guild | Posta o painel no canal fixo de rádio |

---

### P) `cogs/recolhimento.py` — Recolhimento Semanal

Liderança inicia ciclo de dinheiro sujo ou farm no canal. Embeds fixos atualizados a cada entrega via `message.edit()`. Task de fechamento toda sexta 23:59 encerra ciclos abertos.

**Slash Commands:**
| Comando | Permissão | Descrição |
|---------|-----------|-----------|
| `/recolhimento` | Liderança | Inicia ciclo de recolhimento no canal |

---

### Q) `cogs/set_views.py` — Views do Set (Desacoplado)

`SetModal`, `ApprovalView`, `SetPanelView` e utilitários de rate-limit extraídos de `main.py` para desacoplar o entry point e permitir importação segura por outros cogs (ex: `cogs/paineis.py`).

`SET_COOLDOWN_SECONDS = 300`. Dict `_pending_sets` controla cooldown por membro.

---

### R) `services/set_service.py` — Canais Privados

**Funções:**
| Função | Descrição |
|--------|-----------|
| `safe_channel_name(text)` | Sanitiza texto para nome de canal |
| `criar_pasta(guild, member, approver, cat_id, role_ids, id_jogo)` | Cria ou reutiliza canal privado |
| `liberar_pasta(guild, member, guild_id)` | Renomeia para `{n}-livre` ao membro sair |

**Formato do nome:** `{número}-{nome_seguro}-{id_jogo}` (id_jogo appendado como sufixo, sem duplicação)

---

### S) `services/log_service.py` — Log Central

```python
async def send_log(bot, guild: discord.Guild, sistema: str, embed: discord.Embed):
    # Busca canal_log_id em system_config para o sistema
    # Se não configurado: registra no logger local, sem crash
    # Se configurado: envia o embed no canal
```

Usado por: `farm_painel`, `hierarquia`, `acao_painel`, `ausencia`, `encomenda`, `anuncio`

---

### T) `services/db_service.py` — Banco de Dados

Principais grupos de funções:
- **Config:** `db_get_guild_config`, `db_set_guild_config`, `db_is_*_configured`
- **Roles:** `db_get_approver_role_ids`, `db_get_lideranca_role_ids`, `db_get_permitidos_role_ids`
- **Canal privado:** `db_channel_map_get`, `db_channel_map_set`, `db_channel_map_delete`
- **Ausência:** `db_ausencia_get/set/delete`, `db_ausencias_ativos`, `db_ausencia_marcar_avisado`
- **Farm:** `db_lancar(guild_id, week_id, user_id, valores: dict)`, `db_get_progresso`, `db_editar_ultimo_evento`, `db_get_meta`, `db_meta_itens`, `db_prog_itens`, `db_ranking_semana`
- **System Config:** `db_get_system_config(guild_id, sistema)`, `db_set_system_config`, `db_get_all_system_configs`
- **Tempo:** `now_tz()`, `current_week_id()`, `week_id_from(dt)`, `janela_valida()`

---

## 4. BANCO DE DADOS — SCHEMA COMPLETO

### Tabela: `guild_config`
```sql
CREATE TABLE guild_config (
    guild_id               TEXT PRIMARY KEY,
    approval_channel_id    TEXT,    -- canal de aprovação de sets
    log_channel_id         TEXT,    -- canal de log de sets aprovados
    private_category_id    TEXT,    -- categoria para canais privados
    member_role_id         TEXT,    -- cargo aplicado ao aprovar set
    approver_role_ids      TEXT,    -- IDs separados por vírgula
    canal_ausencias_id     TEXT,
    cargos_lideranca_farm  TEXT,    -- IDs separados por vírgula
    cargos_permitidos_farm TEXT,    -- IDs separados por vírgula
    canal_avisos_farm      TEXT,
    canal_notificacao_farm TEXT,
    canal_encomendas_id    TEXT,
    canal_log_saida_id     TEXT,
    canal_anuncio_id       TEXT,
    cargos_anuncio         TEXT,
    dashboard_channel_id   TEXT,    -- canal fixo do dashboard
    dashboard_message_id   TEXT     -- message_id do dashboard postado
)
```

### Tabela: `channel_map`
```sql
CREATE TABLE channel_map (
    guild_id   TEXT,
    user_id    TEXT,
    channel_id TEXT,
    PRIMARY KEY (guild_id, user_id)
)
```

### Tabela: `ausencias`
```sql
CREATE TABLE ausencias (
    guild_id   TEXT,
    user_id    TEXT,
    nome       TEXT,
    dias       INTEGER,
    motivo     TEXT,
    inicio     TEXT,
    fim        TEXT,
    avisado    INTEGER DEFAULT 0,
    message_id TEXT,
    PRIMARY KEY (guild_id, user_id)
)
```

### Tabela: `metas`
```sql
CREATE TABLE metas (
    guild_id     TEXT,
    week_id      TEXT,
    folha        INTEGER DEFAULT 0,
    opio         INTEGER DEFAULT 0,
    seringa      INTEGER DEFAULT 0,
    agulha       INTEGER DEFAULT 0,
    definido_por TEXT,
    definido_em  TEXT,
    itens_json   TEXT,
    PRIMARY KEY (guild_id, week_id)
)
```

### Tabela: `progresso`
```sql
CREATE TABLE progresso (
    guild_id              TEXT,
    week_id               TEXT,
    user_id               TEXT,
    folha                 INTEGER DEFAULT 0,
    opio                  INTEGER DEFAULT 0,
    seringa               INTEGER DEFAULT 0,
    agulha                INTEGER DEFAULT 0,
    status                TEXT DEFAULT 'em_andamento',
    concluida_em          TEXT,
    aprovada              INTEGER DEFAULT 0,
    aprovada_por          TEXT,
    aprovada_em           TEXT,
    painel_channel_id     TEXT,
    painel_message_id     TEXT,
    ultimo_lancamento_em  TEXT,
    itens_prog_json       TEXT,
    aprovacao_antecipada  INTEGER DEFAULT 0,
    aprovacao_nivel       TEXT,
    PRIMARY KEY (guild_id, week_id, user_id)
)
```

### Tabela: `eventos`
```sql
CREATE TABLE eventos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   TEXT,
    week_id    TEXT,
    user_id    TEXT,
    criado_em  TEXT,
    folha      INTEGER DEFAULT 0,
    opio       INTEGER DEFAULT 0,
    seringa    INTEGER DEFAULT 0,
    agulha     INTEGER DEFAULT 0,
    itens_json TEXT
)
```

### Tabela: `system_config`
```sql
CREATE TABLE IF NOT EXISTS system_config (
    guild_id           TEXT NOT NULL,
    sistema            TEXT NOT NULL,
    canal_interacao_id TEXT,
    canal_log_id       TEXT,
    PRIMARY KEY (guild_id, sistema)
)
```

Chaves de sistema usadas: `set`, `farm`, `meta`, `ausencia`, `encomenda`, `acao`, `anuncio`, `hierarquia`

---

## 5. HIERARQUIA DE CARGOS

### Cargos da hierarquia (ordem crescente)
| # | Nome do cargo |
|---|--------------|
| 1 | `\| Pedir Set` |
| 2 | `\| Membro` |
| 3 | `\| Gerente de Recrutamento` |
| 4 | `\| Gerente de Ação` |
| 5 | `\| Gerente de Farm` |
| 6 | `\| Gerente de Produção` |
| 7 | `\| Gerente Geral` |
| 8 | `\| 03` |
| 9 | `\| 02` |
| 10 | `\| 01 Dono` |

### Quem gerencia: `| 01 Dono`, `| 02`, `| 03`

### Cargos ignorados pelo sistema (nunca aparecem como opção):
`| Bots`, `| Programador Dev`, `| Loritta`, `| Rio Bot`, `| Server Booster`, `| Medal`, `| Morro Do Mineiro`, `| Advertência`

---

## 6. MATRIZ DE PERMISSÕES

| Ação | Verificação |
|------|------------|
| Clicar "📝 Fazer Set" | Nenhuma |
| Aprovar/Reprovar Set | `has_approver_permission()` |
| Gerenciar Hierarquia | cargo `\| 01 Dono`, `\| 02` ou `\| 03` |
| Lançar/Ver Farm (painel) | Nenhuma (farm_painel) |
| Editar Farm (painel) | Nenhuma (farm_painel) |
| Iniciar Ação (painel) | Nenhuma (acao_painel) |
| `/setup_*` | `manage_guild` ou `administrator` |
| `/definir_metas`, `/aprovar_farm`, `/editar` | `is_lideranca()` |
| `/lancar`, `/meu_farm` | `is_permitido_farm()` |

---

## 7. COMPONENTES DISCORD (UI) — RESUMO

### Botões persistentes (custom_ids)
| `custom_id` | View | Arquivo |
|-------------|------|---------|
| `set_panel:fazer_set` | `SetPanelView` | `main.py` |
| `approval:aprovar` | `ApprovalView` | `main.py` |
| `approval:reprovar` | `ApprovalView` | `main.py` |
| `ausencia_panel:registrar` | `AusenciaPanelView` | `cogs/ausencia.py` |
| `anuncio:novo` | `AnuncioPainelView` | `cogs/anuncio.py` |
| `acao:entrar` … `acao:encerrar` | `AcaoParticipantesView` | `cogs/acao.py` |
| `farm_painel:lancar` | `FarmPainelView` | `cogs/farm_painel.py` |
| `farm_painel:ver` | `FarmPainelView` | `cogs/farm_painel.py` |
| `farm_painel:editar` | `FarmPainelView` | `cogs/farm_painel.py` |
| `hierarquia:gerenciar` | `HierarquiaPainelView` | `cogs/hierarquia.py` |
| `acao_painel:iniciar` | `AcaoPainelView` | `cogs/acao_painel.py` |
| `dashboard:config_*` | `_DashboardDispatcher` | `cogs/dashboard.py` |
| `dashboard:p1_prev/next` | `_DashboardDispatcher` | `cogs/dashboard.py` |
| `dashboard:p2_prev/next` | `_DashboardDispatcher` | `cogs/dashboard.py` |

---

## 8. DEPLOY

| Item | Valor |
|------|-------|
| Servidor | Oracle Cloud — `ubuntu@163.176.143.142` |
| Diretório remoto | `/home/ubuntu/farmbot` |
| Serviço systemd | `farmbot` |
| Script | `deploy.ps1` (PowerShell) |

---

## 9. LEGADO vs ATUAL

| Arquivo/Recurso | Status | Substituído por |
|-----------------|--------|-----------------|
| `bot.py` | DEPRECIADO | `main.py` |
| `farm.py` (raiz) | DEPRECIADO | `cogs/farm.py` |
| `acao.py` (raiz) | DEPRECIADO | `cogs/acao.py` |
| `ausencia.py` (raiz) | DEPRECIADO | `cogs/ausencia.py` |
| `channel_map.json` | DEPRECIADO | tabela `channel_map` |

---

## 10. BUGS CORRIGIDOS (V2)

### Nome do canal duplicando ID do jogo
- **Problema:** `criar_pasta()` usava `member.display_name` para montar o nome do canal, mas o apelido já havia sido definido como `{nome} | {id_jogo}` antes da chamada. O sufixo `-{id_jogo}` era appendado novamente → `{n}-{nome}-{id_jogo}-{id_jogo}`
- **Correção:** Em `main.py → ApprovalView._processar`, o bloco de criação do canal privado foi movido para ANTES da definição do apelido. Comentário: `# FIX: nome do canal duplicando ID do jogo`

---

## 11. MELHORIAS 2026-05-11

### Painel de Ação — Horário e Tipo antes do Select

- **Melhoria:** Antes de selecionar a ação, o usuário agora informa o horário e o tipo (fuga ou tiro).
- **Arquivos alterados:** `cogs/acao_painel.py`, `cogs/acao.py`

**`cogs/acao_painel.py`:**
- Botão "⚡ Iniciar Ação" agora abre `PreAcaoModal` em vez de postar `AcaoSelectView` diretamente.
- `PreAcaoModal` valida que `tipo_acao` é "fuga" ou "tiro". Se inválido, responde ephemeral de erro.
- O seletor postado no canal inclui campos de horário e tipo no embed.
- Log de ação inclui horário e tipo.

**`cogs/acao.py`:**
- `_build_regras_embed(acao_key, membros_inscritos, horario, tipo)` — novos params opcionais; quando presentes, adiciona campos 🕐 Horário e ⚔️ Tipo no topo do embed.
- `AcaoSelectView(horario, tipo)` — novos params opcionais, repassados ao `AcaoParticipantesView`.
- `AcaoParticipantesView(acao_key, horario, tipo)` — novos params opcionais, repassados a cada `_atualizar_embed`.
- `/acao` slash command não é afetado — chama sem horário/tipo, embed exibe sem esses campos.

---

## 12. MELHORIAS 2026-05-12

### Painel de Ação — Campo de Data + Lista Paginada de Membros

**Arquivos alterados:** `cogs/acao.py`, `cogs/acao_painel.py`

#### Campo de Data (separado do Horário)

**`cogs/acao_painel.py` — `PreAcaoModal`:**
- Adicionado `data` como primeiro `TextInput` (ex: "12/05").
- Modal agora tem 3 campos: Data, Horário, Tipo.
- `on_submit` extrai `data_val` e passa para `AcaoSelectView(horario, tipo, data)`.
- Embed de seleção e log de ação incluem campo `📅 Data`.

**`cogs/acao.py` — `IniciarAcaoModal`:**
- Mesma mudança: campo `data` adicionado, repassado adiante.

**`cogs/acao.py` — `_build_regras_embed`:**
- Novo param `data: str | None = None`.
- Descrição do embed exibe `📅 Data`, `🕐 Hora` e `⚔️ Tipo` (apenas os presentes).

**`cogs/acao.py` — `AcaoSelectView` e `AcaoParticipantesView`:**
- Adicionado param `data` em `__init__`, armazenado em `self.data`, repassado a `_build_regras_embed`.

#### Lista Paginada de Membros (botão "➕ Adicionar membro")

**`cogs/acao.py` — `AdicionarMembroView` → `AdicionarMembroPaginadoView`:**
- `AdicionarMembroView` (usava `user_select` nativo) foi removida.
- Nova classe `AdicionarMembroPaginadoView` exibe um `Select` com membros reais do servidor:
  - Filtra bots e já inscritos; ordena por `display_name`.
  - 20 membros por página (`POR_PAGINA = 20`).
  - Botões ◀ ▶ aparecem quando há mais de uma página.
  - `_rebuild()` reconstrói os componentes a cada navegação.
  - `_on_select`: resolve membro via `guild.get_member()` / `fetch_member()`, valida vagas, insere e atualiza painel.
- Botão `adicionar` em `AcaoParticipantesView` agora monta a lista e abre `AdicionarMembroPaginadoView` (ephemeral).
- Pré-requisito: `intents.members = True` (já ativo em `main.py`).

---

*Análise atualizada após varredura completa da V2 + melhorias de 2026-05-11 + 2026-05-12.*
