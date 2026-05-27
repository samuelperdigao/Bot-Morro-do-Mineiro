# 📋 Documentação dos Painéis — Morro do Mineiro Bot

---

## Setup Inicial

### Painel de Operações + Set (tudo junto)
1. Crie um canal dedicado (ex: `#painel-operacoes`)
2. Execute: `/setup_painel_operacoes`
3. Dois painéis serão postados no mesmo canal: o de **Operações** e o de **Set**

### Painel de Set (separado)
1. Crie um canal dedicado (ex: `#painel-set`)
2. Execute: `/setup_painel_set`
3. Apenas o painel de Set será postado

> ⚠️ **Pré-requisito:** O bot precisa estar configurado com `/setup_bot` antes de usar esses comandos.

---

## O que cada pessoa vê

| Painel         | Todos os usuários veem |
|----------------|------------------------|
| Operações      | 8 botões (os de liderança retornam erro de permissão para membros comuns) |
| Set            | 1 botão — "📝 Pedir Set" |

> **Nota técnica:** Atualmente o painel de operações exibe todos os 8 botões para qualquer membro.
> Membros sem cargo de liderança verão mensagem de erro ephemeral ao clicar em botões restritos.
> Isso é comportamento intencional por enquanto (a view persistente não diferencia por cargo).

---

## Fluxo do Painel de Operações

### Como membro
1. Clique em **🚜 Lançar Farm** → modal de lançamento abre
2. Clique em **📊 Ver Meu Farm** → embed ephemeral com seu progresso da semana
3. Clique em **🏆 Ranking** → top 10 da semana (ephemeral)

### Como liderança (Gerente / Vice / Líder)
1. Todos os botões acima +
2. **✅ Aprovar Farm** → redireciona para `/aprovar_farm`
3. **✏️ Editar Farm** → abre modal de edição do último lançamento
4. **🎯 Definir Metas** → abre modal para definir metas da semana
5. **⚠️ Avisos** → redireciona para `/avisos_farm`
6. **📢 Fazer Anúncio** → abre modal de anúncio

---

## Fluxo do Painel de Set

1. Membro clica **📝 Pedir Set**
2. Preenche **ID no Jogo** (apenas números) + **Nome do Membro**
3. Embed de aprovação é postado no canal de aprovações configurado
4. Gerente clica **✅ Aprovar** ou **❌ Reprovar**
5. Se aprovado:
   - Cargo de membro é atribuído automaticamente
   - Apelido é alterado para `Nome | ID`
   - Canal privado é criado na categoria configurada
   - Embed de boas-vindas é postado no canal privado
   - Log é enviado ao canal de logs

> ⏱️ Cooldown: 5 minutos entre solicitações de set para o mesmo usuário.

---

## Permissões

| Função            | Membro | Gerente | Vice | Líder | Admin/ManageGuild |
|-------------------|:------:|:-------:|:----:|:-----:|:-----------------:|
| Lançar Farm       | ✅*    | ✅      | ✅   | ✅    | ✅                |
| Ver Meu Farm      | ✅*    | ✅      | ✅   | ✅    | ✅                |
| Aprovar Farm      | ❌     | ✅      | ✅   | ✅    | ✅                |
| Editar Farm       | ❌     | ✅      | ✅   | ✅    | ✅                |
| Definir Metas     | ❌     | ✅      | ✅   | ✅    | ✅                |
| Fazer Anúncio     | ❌     | ✅**    | ✅** | ✅**  | ✅                |
| Ver Ranking       | ✅     | ✅      | ✅   | ✅    | ✅                |
| Setup dos Painéis | ❌     | ❌      | ❌   | ❌    | ✅                |

> \* Requer cargo configurado em `/setup_farm` (lista de permitidos)
> \*\* Requer cargo configurado em `/setup_anuncio` (lista de anunciantes)

---

## Persistência após Reinício

Os painéis de Operações e Set sobrevivem a reinícios do bot. As views são registradas como persistentes em `PaineisCog.__init__`. Os IDs de mensagem e canal são salvos no banco (`guild_config`).

> ⚠️ **Atenção:** Solicitações de set pendentes (com botões Aprovar/Reprovar) **perdem a funcionalidade** após reinício do bot. O `ApprovalView` não é registrado como view persistente.

---

## Banco de Dados

Para verificar os painéis configurados:

```bash
python -c "
from services.db_service import get_conn
conn = get_conn()
cur = conn.cursor()
cur.execute('''
    SELECT guild_id,
           painel_operacoes_channel_id, painel_operacoes_message_id,
           painel_set_channel_id,       painel_set_message_id
    FROM guild_config
    WHERE painel_operacoes_channel_id IS NOT NULL
''')
for row in cur.fetchall():
    print(dict(row))
"
```

---

## Logs

Os logs dos painéis são gravados pelo logger `paineis` (saída no console e em `logs/bot.log`).
Os logs do farm estão em `logs/farm.log`.

Ações registradas:
- `lancar_farm: <usuario> (<guild_id>)`
- `ver_meu_farm: <usuario> (<guild_id>)`
- `editar_farm: <usuario> (<guild_id>)`
- `definir_metas: <usuario> (<guild_id>)`
- `fazer_anuncio: <usuario> (<guild_id>)`
- `ranking: <usuario> (<guild_id>)`
- `set_solicitado: <usuario> (<guild_id>)`

---

## Comandos Disponíveis

| Comando                    | Permissão Necessária | Descrição                                    |
|---------------------------|----------------------|----------------------------------------------|
| `/setup_painel_operacoes` | manage_guild         | Posta painel de operações + set no canal     |
| `/setup_painel_set`       | manage_guild         | Posta apenas o painel de set no canal        |
| `/setup_set`              | manage_guild         | Alternativa legada para painel de set        |

---

## Troubleshooting

**Botão retorna "sem permissão":**
- Verifique se o cargo está na lista de permitidos: `/config_ver`
- Configure os cargos com `/setup_farm`
- Para anúncios, configure também com `/setup_anuncio`

**Painel não aparece após reinício:**
- Os painéis não desaparecem — eles já estão no canal
- Os botões são reconectados automaticamente via views persistentes
- Se o bot parou sem registrar as views, execute `/setup_painel_operacoes` novamente

**Aprovação de set não funciona após reinício:**
- Solicitações pendentes no momento do restart perderão os botões
- O solicitante precisará fazer uma nova solicitação via "📝 Pedir Set"

**Painel de set tem dois botões diferentes no servidor:**
- `/setup_set` posta `SetPanelView` (sistema legado de `main.py`)
- `/setup_painel_set` posta `PainelSetView` (sistema novo de `cogs/`)
- Ambos abrem o mesmo `SetModal` — funcionalidade idêntica
- Recomendado: usar apenas `/setup_painel_operacoes` (que inclui o set)

**Membro com `manage_guild` não consegue lançar farm:**
- `is_permitido_farm` exige `administrator` ou cargo configurado
- Usuários com apenas `manage_guild` precisam ter o cargo adicionado manualmente

---

## Arquitetura dos Painéis

```
config/paineis.py          → Configuração visual e de botões (labels, cores, custom_ids)
services/paineis_service.py → Views persistentes + builders de embed
cogs/setup_paineis.py      → Comandos /setup_painel_*
cogs/paineis.py            → Handlers de cliques e lógica de negócio
core/permissions.py        → Funções de verificação de permissão
```
