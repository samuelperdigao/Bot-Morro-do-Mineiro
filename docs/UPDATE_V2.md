# FARMBOT — GRANDE ATUALIZAÇÃO V2

## PASSO 0 — LEITURA OBRIGATÓRIA
Leia o arquivo `CLAUDE.md` na raiz do projeto.
Use-o como fonte de verdade absoluta da arquitetura atual.
Após ler, liste os sistemas encontrados e confirme antes de escrever qualquer código.

---

## FASE 1 — CORREÇÃO DO BUG (execute primeiro)

**Bug:** Na criação do canal privado após aprovação do Set, o ID do jogo
está sendo duplicado no nome do canal.

**Comportamento esperado:** `nome | ID`
**Comportamento atual:** `nome | ID | ID`

Localize onde o nome do canal é montado no fluxo de aprovação.
Corrija de forma cirúrgica sem alterar nada do restante do fluxo.
Documente com comentário: `# FIX: nome do canal duplicando ID do jogo`

---

## FASE 2 — DASHBOARD DE CONFIGURAÇÃO

Criar o sistema de configuração central do bot.
Canal fixo do dashboard: `1494692392052461588`

### Comando `/setup_dashboard`
- Restrito a `manage_guild`
- Posta o embed do dashboard no canal `1494692392052461588`
- Salva o `message_id` no banco para edições futuras

### Design do painel (embed paginado)

**Página 1/2:**
- 🎮 Sistema de Set — Configure o sistema de set no servidor
- 🌾 Sistema de Farm — Configure o sistema de farm no servidor
- 🎯 Sistema de Meta — Configure o sistema de meta no servidor
- 🏖️ Sistema de Ausência — Configure o sistema de ausência no servidor
- 📦 Sistema de Encomenda — Configure o sistema de encomenda no servidor
- ⚡ Sistema de Ação — Configure o sistema de ação no servidor
- 📢 Sistema de Anúncio — Configure o sistema de anúncio no servidor

**Página 2/2:**
- 👑 Sistema de Hierarquia — Configure o sistema de hierarquia no servidor

Cada item tem botão ≡ ao lado.
Navegação: botões ← → no rodapé.

### Modal de configuração (ao clicar em ≡ de qualquer sistema)

Dois campos:
- **Canal de Interação:** onde o painel fixo desse sistema fica postado (placeholder: "Cole o ID do canal")
- **Canal de Log:** onde as interações serão registradas (placeholder: "Cole o ID do canal")

Ao confirmar:
- Salva no banco SQLite
- Responde com embed ephemeral confirmando os canais salvos em formato <#ID>

### O dashboard é soberano
As configurações feitas pelo dashboard sobrescrevem qualquer `/setup` existente.
Os comandos `/setup` existentes continuam funcionando por compatibilidade,
mas devem ler e escrever na mesma tabela do dashboard.

### Persistência
Criar tabela `system_config` no farm.db se não existir:

```sql
CREATE TABLE IF NOT EXISTS system_config (
    guild_id TEXT NOT NULL,
    sistema TEXT NOT NULL,
    canal_interacao_id TEXT,
    canal_log_id TEXT,
    PRIMARY KEY (guild_id, sistema)
);
```

Usar INSERT OR REPLACE. Não deletar dados existentes.

### Arquivo: `cogs/dashboard.py`
Toda lógica do dashboard neste arquivo.
Registrar no `main.py` sem remover cogs existentes.

---

## FASE 3 — PAINEL DE FARM (canal fixo para membros)

Criar um embed fixo no canal configurado para farm (via dashboard).
Substituir o acesso pelo painel de operações atual para esses três itens.

### Botões do painel:
- 🚜 Lançar Farm
- 📊 Ver Meu Farm
- ✏️ Editar Farm

### Design dos modais (padrão visual: dourado #FFD700, dark, premium)

**Modal Lançar Farm:**
- Título: "🚜 Lançar Farm — Morro do Mineiro"
- Campo: Quantidade farmada (placeholder: "Ex: 5000")
- Embed de confirmação após envio com: nome do membro, quantidade, timestamp
- Envia log para canal de log do farm (configurado no dashboard)

**Modal Ver Meu Farm:**
- Não abre modal — abre uma resposta ephemeral com embed mostrando
  o farm atual do membro (total farmado, meta, % atingida)
- Design premium com barra de progresso em texto (ex: ▓▓▓▓░░░░ 60%)

**Modal Editar Farm:**
- Título: "✏️ Editar Farm — Morro do Mineiro"
- Campo: Novo valor (placeholder: "Ex: 7000")
- Campo: Motivo da edição
- Envia log para canal de log do farm com: quem editou, valor anterior,
  novo valor, motivo, timestamp

### Log do farm (embed no canal de log):
- Cor: dourada (#FFD700)
- Campos: membro, ação realizada, valores, timestamp
- Footer: "Morro do Mineiro — Sistema de Farm"

### Arquivo: `cogs/farm_painel.py`
Manter `cogs/farm.py` existente intacto.
O novo painel é um cog separado que usa os mesmos services.

---

## FASE 4 — SISTEMA DE HIERARQUIA

Criar painel fixo de gerenciamento de cargos.

### Quem pode usar: cargos | 01 Dono, | 02, | 03

### Fluxo:
1. Painel fixo no canal configurado (via dashboard)
2. Botão "👑 Gerenciar Hierarquia"
3. Abre Select Menu com lista de membros do servidor
4. Após selecionar o membro, abre segundo Select Menu com os cargos disponíveis
5. Confirmar aplica o cargo e remove o anterior da hierarquia

### Hierarquia de cargos (do menor ao maior):
1. | Pedir Set
2. | Membro
3. | Gerente de Recrutamento
4. | Gerente de Ação
5. | Gerente de Farm
6. | Gerente de Produção
7. | Gerente Geral
8. | 03
9. | 02
10. | 01 Dono

### Cargos ignorados pelo sistema (nunca aparecem como opção):
| Bots, | Programador Dev, | Loritta, | Rio Bot,
| Server Booster, | Medal, | Morro Do Mineiro, | Advertência

### Log de hierarquia (embed no canal de log):
- Cor: dourada (#FFD700)
- Campos: quem executou a ação, membro afetado, cargo anterior,
  novo cargo, tipo (PROMOÇÃO ou REBAIXAMENTO), timestamp
- Footer: "Morro do Mineiro — Sistema de Hierarquia"

### Arquivo: `cogs/hierarquia.py`

---

## FASE 5 — PAINEL DE AÇÃO (canal fixo)

Manter toda a lógica atual do `/acao` intacta.
Criar embed fixo no canal configurado (via dashboard) com botão para iniciar.
Ao iniciar, a interação é redirecionada para o canal de ação configurado.
Log enviado para canal de log da ação (configurado no dashboard).

### Arquivo: `cogs/acao_painel.py`
Manter `cogs/acao.py` existente intacto.

---

## FASE 6 — INFRAESTRUTURA DE LOGS

Criar `services/log_service.py` com função central:

```python
async def send_log(bot, guild: discord.Guild, sistema: str, embed: discord.Embed):
    # Busca canal_log_id na tabela system_config para o sistema
    # Se não configurado: registra no logger local, sem crash
    # Se configurado: envia o embed no canal
```

Todos os painéis criados nas fases anteriores devem usar esta função.
Sistemas já existentes (ausencia, encomenda, anuncio) devem ter
chamadas de log adicionadas nos pontos de ação.

---

## FASE 7 — ATUALIZAR O CLAUDE.md

Após concluir todas as fases, reescrever o `CLAUDE.md` com:
- Estrutura de arquivos atualizada
- Todos os sistemas e cogs descritos
- Esquema completo do banco (todas as tabelas e colunas)
- ID do canal do dashboard: `1494692392052461588`
- Hierarquia de cargos documentada
- Bugs corrigidos nesta sessão
- Padrão visual: dourado #FFD700, dark, premium

---

## REGRAS GERAIS
- Não remova nenhum comando, cog, view ou modal existente
- Não altere farm.db além de criar novas tabelas necessárias
- Cada fase deve ser confirmada antes de iniciar a próxima
- Se encontrar ambiguidade, pergunte antes de decidir
- Ao finalizar cada fase, liste exatamente o que foi criado e modificado