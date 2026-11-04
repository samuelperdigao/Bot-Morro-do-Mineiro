# ENCOMENDA — FASE 1: Fluxo Registro → Pedidos → Entregues

> Prompt de implementação para o Claude Code. Leia o arquivo inteiro antes de escrever qualquer código.
> Idioma do código, comentários, logs e mensagens ao usuário: **português do Brasil**.

---

## 1. Contexto

Bot Discord do servidor "Morro do Mineiro" (discord.py **2.3.2**, SQLite WAL, cogs, Oracle Cloud via systemd `farmbot`).

Hoje o sistema de encomendas (`cogs/encomenda.py`) só posta um embed solto no canal configurado. **Não existe tabela, status, histórico nem consulta.** A encomenda existe apenas como mensagem.

### Objetivo da Fase 1

Transformar isso em um fluxo com ciclo de vida, usando 3 canais:

```
#encomendas (painel fixo)     #pedidos (ativos)                    #entregues (arquivo)
[📦 Registrar Encomenda] ──►  1 embed vivo por encomenda     ──►   embed final, sem botões
        (modal)               com botões de status                  ✅ Entregue ou ❌ Cancelada
```

1. Membro clica em **Registrar** no painel e preenche o modal.
2. Bot grava no banco (número sequencial por servidor: #001, #002…) e posta o pedido em `#pedidos` com status **Pendente**.
3. Quem tem permissão usa os botões do embed: **Em produção**, **Pronta**, **Entregue**, **Cancelar**. O mesmo embed é editado a cada clique (status, cor, responsável).
4. **Entregue** e **Cancelar** pedem confirmação. Ao confirmar: o bot posta a versão final em `#entregues`, apaga o embed de `#pedidos` e registra tudo no banco.
5. O solicitante é avisado a cada mudança de status.

---

## 2. Leitura obrigatória antes de codar

Leia e entenda estes arquivos. Não presuma nada que não tenha visto:

- `cogs/encomenda.py` — implementação atual (modal, `EncomendaPainelView`, `/encomenda`, `/setup_encomenda_painel`)
- `cogs/setup.py` — `/setup_encomenda`
- `cogs/bau_core.py` e `tests/test_bau_core.py` — **padrão de referência** para camada de regras separada do Discord + testes com SQLite temporário
- `services/db_schema.py` (`SCHEMA_SQL`, `MIGRATIONS`, `ensure_schema`) **e** `services/db_service.py` (`init_db`, `get_conn`, `db_get_system_config`, `db_set_system_config`) — **confirme qual caminho realmente cria as tabelas na inicialização** e siga o mesmo caminho
- `services/log_service.py` (`send_log`)
- `config/paineis.py` (`NIVEIS_ACESSO`, `NIVEIS_LIDERANCA`, permissão `encomenda`) e `services/paineis_service.py` — descubra **qual helper existente resolve o nível de acesso de um membro** (procure por usos de `NIVEIS_LIDERANCA`) e reutilize-o
- `core/date_utils.py` (`normalize_date_br`, `DATE_BR_EXAMPLE`), `core/logger.py`, `core/extensions.py`
- `promps/CLAUDE.md` (seção I) e `CHANGELOG.md`

Antes de implementar, escreva um **plano curto** (arquivos que vai criar/alterar e por quê) e só então comece.

---

## 3. Restrições (não negociáveis)

- **discord.py 2.3.2**: NÃO use `DynamicItem` nem nada de versões posteriores.
- **Botões persistentes** sobrevivem a restart: view com `timeout=None`, `custom_id` fixo, registrada com `bot.add_view(...)` na inicialização do cog (mesmo padrão do `EncomendaPainelView` atual). O pedido é identificado pelo **ID da mensagem** (`interaction.message.id`) consultando o banco, nunca pelo `custom_id`.
- Camada de regras **sem import de discord** em `services/encomenda_core.py`. O cog só faz interface.
- Banco: SQLite via `get_conn()` existente. Colunas novas em tabelas existentes entram em `MIGRATIONS`. Tabelas novas entram em `SCHEMA_SQL`.
- Não alterar `.env`, `deploy.ps1`, nem fazer deploy. Não commitar sem eu pedir.
- Para editar arquivos grandes, **reescreva o trecho/arquivo completo**; não use `sed` (já corrompeu arquivos neste projeto).
- Não quebrar o que existe: manter `custom_id` do painel atual (`encomenda_painel:registrar`), `/encomenda`, `/setup_encomenda`, `/setup_encomenda_painel`.
- Qualquer operação de transição de status deve ser **atômica** (ver 4.3).
- Nunca deixar estoque/valor negativo; quantidade e valor precisam ser > 0.

---

## 4. Especificação

### 4.1 Banco de dados

**Tabela `encomendas`:**

| Coluna | Tipo | Observação |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `guild_id` | TEXT NOT NULL | |
| `numero` | INTEGER NOT NULL | sequencial por servidor; `UNIQUE (guild_id, numero)` |
| `familia` | TEXT NOT NULL | |
| `quantidade` | INTEGER NOT NULL | > 0 |
| `valor_centavos` | INTEGER NOT NULL | > 0 |
| `data` | TEXT NOT NULL | formato retornado por `normalize_date_br` |
| `observacao` | TEXT | opcional |
| `status` | TEXT NOT NULL DEFAULT 'pendente' | ver 4.3 |
| `solicitante_id` | TEXT NOT NULL | |
| `responsavel_id` | TEXT | quem moveu para "Em produção" (ou, se pulou, quem fez a 1ª transição) |
| `pedidos_channel_id`, `pedidos_message_id` | TEXT | |
| `arquivo_channel_id`, `arquivo_message_id` | TEXT | |
| `criado_em`, `atualizado_em`, `finalizado_em` | TEXT | ISO 8601 |

Índices: `(guild_id, status)` e `(pedidos_message_id)`.

**Tabela `encomenda_eventos`** (histórico): `id`, `encomenda_id` (FK lógica), `tipo` (`criada`, `status`, `erro`), `de_status`, `para_status`, `user_id`, `detalhe`, `criado_em`.

**Configuração dos canais** — adicionar em `system_config` via `MIGRATIONS` (para sistema `encomenda`):
- `canal_pedidos_id TEXT`
- `canal_entregues_id TEXT`

`canal_interacao_id` continua sendo o canal do painel de registro; `canal_log_id` continua sendo o log. Criar helpers em `db_service.py` para ler/gravar os dois novos campos **sem sobrescrever** `canal_interacao_id`/`canal_log_id` (cuidado: `db_set_system_config` atual faz upsert dessas duas colunas).

### 4.2 `services/encomenda_core.py` (puro, sem discord)

Funções puras:
- `parse_quantidade(texto) -> int` — aceita "50", " 50 ". Rejeita vazio, texto, <= 0. Levanta `ValueError` com mensagem amigável.
- `parse_valor_centavos(texto) -> int` — aceita `1500`, `1500,50`, `1.500`, `1.500,00`, `R$ 1.500,00`. Rejeita <= 0 e formatos ambíguos/absurdos (ex.: `1,5,0`). Levanta `ValueError`.
- `format_brl(centavos) -> str` — `150000` → `R$ 1.500,00`.
- `formatar_numero(n) -> str` — `3` → `#003`.

Constantes:
```python
STATUS = ("pendente", "em_producao", "pronta", "entregue", "cancelada")
STATUS_ATIVOS = ("pendente", "em_producao", "pronta")
STATUS_FINAIS = ("entregue", "cancelada")
TRANSICOES = {
    "pendente":    {"em_producao", "pronta", "entregue", "cancelada"},
    "em_producao": {"pronta", "entregue", "cancelada"},
    "pronta":      {"entregue", "cancelada"},
}
```
(Só avança — pode pular etapas, nunca volta. Estados finais não saem.)

Exceções: `TransicaoInvalidaError`, `EncomendaDesatualizadaError` (outra pessoa já mudou o status), `EncomendaNaoEncontradaError`.

Classe `EncomendaRepository(conn)` (padrão do `BauRepository`):
- `criar(guild_id, familia, quantidade, valor_centavos, data, observacao, solicitante_id) -> row` — número = `MAX(numero)+1` por guild **dentro de transação** (`BEGIN IMMEDIATE`), grava evento `criada`.
- `obter(id)`, `obter_por_mensagem_pedidos(message_id)`
- `salvar_mensagem_pedidos(id, channel_id, message_id)`, `salvar_mensagem_arquivo(id, channel_id, message_id)`
- `transitar(id, novo_status, user_id) -> row` — valida contra `TRANSICOES`; faz `UPDATE ... WHERE id=? AND status=?` e confere `rowcount`; se 0 → `EncomendaDesatualizadaError`. Preenche `responsavel_id` na primeira transição, `finalizado_em` ao finalizar, grava evento `status`.
- `listar_ativas(guild_id)` (útil para a Fase 2)
- `excluir(id)` — usado **apenas** para desfazer a criação se o envio do embed em `#pedidos` falhar.

### 4.3 Cog `cogs/encomenda.py` (reescrever completo)

**Modal `EncomendaModal`** — 5 campos: Família, Quantidade, Valor (R$), Data da Encomenda, Observação (opcional, parágrafo, max 300). Validar tudo via core **antes** de qualquer escrita; erro → mensagem ephemeral clara, sem gravar nada.

**Registro:**
1. Resolver canais. Se `canal_pedidos_id` não estiver configurado ou o canal não existir → ephemeral: "Canais não configurados. Use `/setup_encomenda_canais`." e **não grava**.
2. `repo.criar(...)`.
3. Postar embed em `#pedidos` com `PedidoView`. Se falhar (Forbidden/HTTP) → `repo.excluir(id)`, avisar o usuário, logar o erro. Nunca deixar registro sem mensagem.
4. Salvar ids da mensagem; `send_log(..., "encomenda", ...)`.
5. Resposta ephemeral: "✅ Encomenda #003 registrada em #pedidos".

**Embed** (função `build_embed(row, guild)` reutilizada em pedidos e entregues):
- Título `📦 Encomenda #003`; cor por status: pendente laranja (230,126,34), em produção azul, pronta dourado, entregue verde, cancelada vermelho.
- Campos: Família, Quantidade, Valor (`format_brl`), Data, Status (com emoji), Solicitante (menção), Responsável (menção ou "—"), Observação (se houver).
- Footer: "Morro do Mineiro — Encomendas"; timestamp = `atualizado_em`.

**`PedidoView`** (persistente) — 4 botões com `custom_id` fixos: `encomenda_pedido:producao`, `:pronta`, `:entregue`, `:cancelar`. Ao editar a mensagem, enviar uma instância da view com botões **desabilitados** conforme o status (ex.: "Em produção" desabilitado quando já está em produção ou além). Os `custom_id` não mudam, então a persistência continua valendo.

**Handler dos botões:**
1. Buscar encomenda por `interaction.message.id`. Não achou → ephemeral "Encomenda não encontrada no banco".
2. **Permissão:** só nível `lider`, `vice_lider` ou `gerente` (reutilize o helper existente que resolve nível; administrador do servidor também passa). Sem permissão → ephemeral.
3. **Em produção / Pronta:** `transitar`, editar a mensagem do pedido (embed + view), avisar solicitante, `send_log`.
4. **Entregue / Cancelar:** mostrar ephemeral com botões "Confirmar" / "Voltar" (view com timeout 60s, só quem clicou pode confirmar). No confirmar: `transitar`, postar embed final em `#entregues` (sem view; para cancelada pode incluir quem cancelou), salvar ids do arquivo, **apagar** a mensagem em `#pedidos` (ignorar `NotFound`), avisar solicitante, `send_log`.
5. `EncomendaDesatualizadaError` → ephemeral "Alguém já atualizou esta encomenda. Atualize a tela." e re-sincronizar a mensagem do pedido com o estado do banco.
6. Se `#entregues` não estiver configurado/acessível no momento de finalizar → **não finalizar**; ephemeral explicando; nada é alterado.

**Aviso ao solicitante:** tentar DM com embed curto; se falhar (DMs fechadas), ignorar silenciosamente — no caso de **Entregue/Cancelada**, colocar a menção do solicitante no `content` da mensagem postada em `#entregues`. Nunca deixar uma falha de notificação quebrar a transição.

**Comandos:**
- `/setup_encomenda_canais pedidos:#canal entregues:#canal` (`manage_guild`) — grava `canal_pedidos_id` e `canal_entregues_id`. Validar que o bot tem permissão de enviar mensagens/embeds nos dois.
- Manter `/setup_encomenda`, `/setup_encomenda_painel` e `/encomenda` funcionando; `/encomenda` abre o mesmo modal.
- Atualizar o texto do embed do painel fixo explicando o fluxo (registro → acompanhamento em #pedidos).

### 4.4 Dashboard

**Não mexer em `cogs/dashboard.py` na Fase 1.** A configuração dos 2 canais novos é feita só pelo `/setup_encomenda_canais`. (Integração com o dashboard fica para depois.)

### 4.5 Testes — `tests/test_encomenda_core.py`

`unittest` + SQLite temporário, mesmo estilo de `tests/test_bau_core.py`. Cobrir no mínimo:
- `parse_valor_centavos`: `"1.500,00"`, `"1500"`, `"1500,5"`, `"R$ 1.500,00"`, `"0"`, `"-5"`, `"abc"`, `"1,5,0"`.
- `parse_quantidade`: válido, `0`, negativo, texto, vazio.
- `format_brl` e `formatar_numero`.
- Numeração sequencial por servidor (dois guilds não se misturam).
- Todas as transições válidas e inválidas (incluindo sair de estado final e voltar).
- `EncomendaDesatualizadaError` quando o status mudou entre leitura e escrita.
- Concorrência: várias threads tentando a mesma transição → exatamente uma vence.
- Eventos gravados em criação e em cada transição.
- `excluir` remove o registro.

Rodar a suíte inteira (`python -m unittest discover tests` ou o comando que o projeto já usa) e garantir que **nada que já passava quebrou**.

### 4.6 Documentação

- `promps/CLAUDE.md`: atualizar a seção I (Encomendas) com o fluxo, comandos novos, tabelas e canais.
- `CHANGELOG.md`: nova entrada com data de hoje no mesmo formato das anteriores.

---

## 5. Fora do escopo (NÃO fazer agora)

- Itens estruturados/catálogo, baixa de estoque do Baú
- `/encomendas` (listagem/filtros), edição de encomenda, botão "Assumir"
- Relatórios, lembrete de prazo
- Dashboard, MDM Tablet
- Migração das encomendas antigas (eram só mensagens soltas)

Se identificar algo importante fora do escopo, **anote no resumo final**; não implemente.

---

## 6. Critérios de aceite

- [ ] Registrar uma encomenda grava no banco, cria `#00N` e posta em `#pedidos` com 4 botões.
- [ ] Os botões continuam funcionando **após reiniciar o bot** (`sudo systemctl restart farmbot`).
- [ ] Membro sem nível de liderança não consegue mudar status.
- [ ] Entregue/Cancelar exigem confirmação, movem o embed para `#entregues` sem botões e apagam o de `#pedidos`.
- [ ] Dois cliques simultâneos não geram transição dupla.
- [ ] Falha ao postar em `#pedidos` não deixa registro órfão.
- [ ] Canais não configurados → erro claro, nada gravado.
- [ ] Valores/quantidades inválidos são rejeitados antes de gravar.
- [ ] Todos os testes passam (novos e antigos).
- [ ] Nenhum arquivo fora do escopo alterado sem justificativa.

---

## 7. Entrega

Ao terminar, responda com:
1. Lista de arquivos criados/alterados (uma linha cada).
2. Resultado da suíte de testes.
3. **Checklist de teste manual no Discord** (passo a passo curto, na ordem para eu executar após o deploy).
4. Riscos ou pontos que exigem minha decisão.

Não faça deploy nem commit.
