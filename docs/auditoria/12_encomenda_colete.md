# Encomendas + Fabricação de Coletes

## Resumo
- **O que faz:** `cogs/encomenda.py` tem um painel com botão e o comando `/encomenda`. Os dois abrem um modal (família, quantidade, valor, data) que só posta um embed no canal e manda um log. `cogs/colete.py` tem um painel fixo com select de 1 a 10 coletes: mostra os materiais e o custo, pede confirmação e um print, e grava em `fabricacoes_colete`.
- **Estado geral:** funciona no caminho feliz e o cálculo está certo (os testes passam), mas os dois módulos estão incompletos. A encomenda **não persiste nada** (não existe status pendente/entregue, histórico nem responsável). O colete **não tem integração nenhuma com o baú**: não dá baixa de materiais, não dá entrada de "Colete" e não valida saldo. O log é *hardcoded* para um único servidor. Um único print pode registrar várias fabricações.
- **Nota: 4,5/10.** A base é limpa e simples, mas o módulo não cumpre o papel de controle de produção e de pedidos.

> Testes: `tests/test_colete.py` → **3 passed, 2 subtests passed**. Rodei numa cópia (`git archive`) em venv com discord.py 2.3.2 e `DISCORD_TOKEN`/`APPLICATION_ID` fictícios. Importar `core/config.py` cria `data/` no repositório (`DATA_DIR.mkdir`), por isso o repo original não foi tocado. Os testes cobrem **apenas** `calcular_fabricacao`.

---

## Bugs / quebras

| Severidade | arquivo:linha | problema | correção sugerida |
|---|---|---|---|
| **Alta** | `cogs/colete.py:158-170` | **Um print confirma N fabricações.** O usuário pode abrir várias confirmações (o select é persistente e cada escolha cria um `ColeteConfirmView` novo) e clicar "CONFIRMAR" em todas. O `check` só filtra autor + canal + imagem. Em discord.py 2.3.2, `Client.dispatch` (`client.py:465-486`) resolve **todos** os listeners cujo check passa, então a mesma mensagem acorda todos os `wait_for` e cada um chama `db_registrar_fabricacao_colete`. Isso dá duplicação de produção (e de baixa no baú, se ela for integrada). | Usar um lock/estado por `(guild_id, user_id)`, por exemplo `self._pendentes: set` no cog: recusar uma segunda confirmação enquanto houver outra aguardando o print. Opcionalmente gravar `message.id` do print com `UNIQUE` na tabela. |
| **Alta** | `cogs/colete.py:34` e `:256-263`; `cogs/dashboard.py:49-59` | **O log de fabricação só funciona num servidor.** `LOG_FABRICACAO_CHANNEL_ID = 1506880362633236630` é fixo. O sistema `"colete"` não existe em `SISTEMAS` do dashboard, então `system_config.canal_log_id` do colete nunca é preenchido. Nos outros servidores `send_log` tenta o ID fixo, `Guild.fetch_channel` levanta `InvalidData` (canal de outra guild), o log se perde e o usuário vê "não foi possível enviar o log". Isso fere o requisito multi-servidor. | Adicionar `{"key": "colete", ...}` em `SISTEMAS`, ler o canal de log de `system_config` e remover o fallback fixo (ou movê-lo para env/config por guild). |
| **Alta** (funcional) | `cogs/colete.py:203-215` | **Nenhuma integração com o baú.** A fabricação só grava em `fabricacoes_colete` (farm.db). Não há baixa de Ferro/Plástico/Tecido/Alumínio/Borracha em `bau_estoque`, nem entrada de "Colete", nem validação de saldo. O estoque do baú e a produção divergem e é possível "fabricar" sem material. | Chamar `repo.apply_operation("saida", [...], origin="colete", operation_id=...)` (`cogs/bau_core.py:388-512`, que já é atômico com `BEGIN IMMEDIATE`, valida saldo com `StockInsufficientError` e é idempotente por `operation_id`) **antes** de pedir o print, ou na confirmação. Mapear chaves → `"Ferro","Plástico","Tecido","Alumínio","Borracha"` e depois dar `entrada` de `"Colete"`. Ver "Melhorias técnicas", item 3. |
| **Alta** (funcional) | `cogs/encomenda.py:78-149` | **A encomenda não é persistida.** Não existe tabela, ID nem status (pendente/entregue). Ninguém consegue marcar como entregue, listar abertas ou somar valores. Se a mensagem for apagada, o registro some. | Criar a tabela `encomendas` (id, guild_id, familia, quantidade INT, valor INT, data_pedido, prazo, status, criado_por, responsavel_id, message_id, channel_id, entregue_por, entregue_em) e uma view persistente com botões de status na mensagem publicada. |
| **Média** | `cogs/colete.py:198-215` | **Erro de DB depois de apagar o print deixa o usuário travado.** O print é apagado (`message.delete()`) **antes** do `INSERT`, e o `INSERT` não tem try/except. Se o SQLite falhar (lock ou disco), a exceção vai para `View.on_error` padrão (só loga). A mensagem ephemeral fica em "Aguardando print" para sempre e a prova já foi apagada. | Gravar primeiro e apagar depois. Envolver o `INSERT` em try/except com um embed de erro, ou implementar `on_error` na view. |
| **Média** | `cogs/colete.py:308-323` | **SUSPEITA (comportamento conhecido do cliente Discord):** o select persistente não é resetado depois da escolha. O cliente mantém a opção marcada, e escolher **a mesma quantidade de novo** não dispara interação até recarregar. | Depois do `send_message`, fazer `await interaction.message.edit(view=ColetePanelView())`, ou responder com `edit_message` + `followup`, para limpar a seleção. |
| **Média** | `cogs/colete.py:316-323`, `cogs/encomenda.py:175-176`, `:239-258` | **Não há checagem de cargo.** Qualquer membro que vê o canal registra fabricação e encomenda. `config/paineis.py:35` define `"encomenda": [...]`, mas `PERMISSOES_PAINEL_OPERACOES` não é usado em nenhum lugar (grep). | Adicionar `interaction_check` nas views usando os níveis de `config/paineis.py`. Para status/entrega, restringir a `NIVEIS_LIDERANCA`. |
| **Média** | `cogs/encomenda.py:62-71` | Quantidade e valor são texto livre ("abc", "-5", "1k"). Com isso não dá para somar e o relatório fica impossível. | Fazer o parse com `int`/decimal BR (`1.500,00` → 150000 centavos) e rejeitar ≤0 com mensagem clara. |
| **Média** | `cogs/encomenda.py:224` | `/setup_encomenda_painel` não guarda o `message_id` nem apaga o painel antigo. Cada execução duplica o painel (o `/colete` faz isso certo em `colete.py:344-366`). | Guardar `painel_encomenda_channel_id/message_id` e apagar o antigo, como no colete. |
| **Baixa** | `cogs/encomenda.py:29-35` + `:204` | O painel é postado em `canal_interacao_id` e as encomendas são postadas no **mesmo** canal (`_get_encomenda_channel` prioriza `canal_interacao_id`). O painel vai sendo empurrado para cima e some do topo. | Publicar as encomendas no `canal_log_id` ou num canal "fila" separado, ou repostar o painel no fim (sticky). |
| **Baixa** | `cogs/colete.py:144-146` | `ColeteConfirmView(timeout=180)` não tem `on_timeout`. Depois de 3 min sem clique os botões continuam ativos e clicar resulta em "Esta interação falhou". | Implementar `on_timeout` que desativa os itens e edita a mensagem (guardar `interaction` em `self`). |
| **Baixa** | `cogs/encomenda.py:110` | `f"```{self.familia.value}```"`: uma família com "```" quebra o bloco de código do embed. | `discord.utils.escape_markdown` ou trocar a crase por `ˋ`. |
| **Baixa** | `cogs/encomenda.py:119-149` | O sucesso ao usuário (`:121`) e o `send_log` (`:140`) estão no mesmo `try`. Uma exceção depois do sucesso (ex.: `db_get_system_config` dentro de `send_log`) também manda "Erro inesperado", e o usuário recebe as duas mensagens. | Isolar o log em um try próprio. |
| **Baixa** | `cogs/encomenda.py:239-243` | `/encomenda` sem `@app_commands.guild_only()`. Na DM, `guild_id=None` vira a string `"None"` na consulta. Não quebra hoje só porque cai em "não configurado". | Adicionar `guild_only()`. |
| **Baixa (SUSPEITA)** | `services/log_service.py:34-47` | No fallback para o 2º canal, o mesmo `discord.File` é reenviado. Depois da 1ª tentativa o `BytesIO` fica no fim (o `reset(seek=tries)` com `tries=0` não faz seek), então o 2º envio pode sair com o anexo vazio. | Chamar `f.reset()`/`fp.seek(0)` antes de cada envio, ou recriar os `File`. |
| **Baixa** | `cogs/colete.py:158-163` | Qualquer imagem que o usuário poste no canal nos próximos 3 min vale como "print", mesmo sem relação com a fabricação. Se o membro não tiver permissão de anexar arquivos no canal, ele fica travado até o timeout. | Checar `channel.permissions_for(member).attach_files` antes. Ou aceitar o print via modal/attachment de slash, ou numa thread privada. |

---

## Melhorias visuais/UX (prioridade)
1. **Padrão visual quebrado.** As cores atuais são `0x34495E` (painel, `colete.py:74`), `0xF1C40F` (`:88`, `:108`, `:226`) e laranja `230,126,34` (`encomenda.py:24`). O padrão é **#FFD700**. Os footers também não seguem o padrão: `"Morro do Mineiro"` (`colete.py:76`), `"Morro do Mineiro - Fabricacao de Coletes"` (`:254`), `"Registrado por X"` (`encomenda.py:115`), `"Sistema de Encomendas"` vs `"Sistema de Encomenda"` (`:223` vs `:139`). O alvo é `Morro do Mineiro — Sistema de Coletes/Encomendas`, com `set_footer(icon_url=guild.icon)`.
2. **Texto sem acentos no colete:** "FABRICACAO", "Plastico", "Aluminio", "e o limite", "voce precisara" (`colete.py:65-111`). Para uma comunidade BR premium soa amador. Restaurar os acentos e usar emojis temáticos (🛡️ colete, 🔩 ferro, 🧴 plástico, 🧵 tecido, ⚙️ alumínio, 🛞 borracha).
3. **Moeda inconsistente:** o colete mostra `$10,000` (`colete.py:49`, padrão US) e a encomenda `R$ 1.500,00`. Padronizar em `R$ 10.000` com um helper único.
4. **Confirmação do colete:** mostrar o **saldo atual do baú vs necessário** por material (✅/❌), já com a integração. Desabilitar "Confirmar" quando faltar material.
5. **Embed da encomenda:** incluir o **ID da encomenda** (`#0042`), **status** (badge 🟡 Pendente / 🟢 Entregue / 🔴 Cancelada), responsável, prazo e valor unitário calculado (valor ÷ quantidade).
6. **Sucesso do colete:** incluir um link para a mensagem de log (`jump_url`) e o total acumulado do membro na semana.
7. **Painel do colete:** com 10 opções, as descrições no select (71 chars em qtd=10, abaixo do limite de 100) estão poluídas. Mostrar apenas "Custo R$ X · Ferro X" e deixar o detalhe para o embed de confirmação.
8. **Painel de encomenda:** a descrição atual é genérica. Mostrar os contadores "📋 Pendentes: N · ✅ Entregues hoje: N".

## Melhorias técnicas (prioridade)
1. **Lock de concorrência por usuário** no fluxo de print do colete (corrige o bug Alta #1).
2. **Persistência de encomendas** com status e view persistente de ações (`custom_id="encomenda:status:<id>"` com `DynamicItem`, ou um único `custom_id` mais lookup pelo `message_id`).
3. **Integração atômica colete → baú.** O baú está em `bau.db` e a fabricação em `farm.db`, então não dá para usar uma transação única. Sequência proposta:
   1. Gerar `operation_id = uuid4().hex`.
   2. `repo.apply_operation("saida", materiais, origin="colete", operation_id=op)`. Já valida o saldo e é idempotente.
   3. Gravar a fabricação com a coluna nova `bau_operation_id`.
   4. Em caso de falha (timeout do print, erro de DB), estornar com `undo_items`, que já existe em `bau_core.py:668`.
   - Ideal: um método `apply_transform(saida=[...], entrada=[("Colete", qtd)])` na mesma transação `BEGIN IMMEDIATE`.
   - **Atenção:** `bau_estoque` não tem `guild_id` (`bau_core.py:254-258`) e `cogs/bau.py:36` tem o `CANAL_BAU_ID` fixo. O baú é single-guild, então a integração precisa ficar restrita ao servidor dono do baú, ou o baú precisa ganhar `guild_id`.
4. **Configuração do colete no dashboard** (`SISTEMAS` + `system_config`) e remoção dos IDs fixos.
5. **Receita configurável:** `MATERIAIS_POR_COLETE`/`CUSTO_POR_COLETE` são constantes (`colete.py:24-31`). Mover para uma tabela/config por guild, para mudar o preço sem deploy.
6. **Índice** `CREATE INDEX idx_fab_colete_guild_ts ON fabricacoes_colete(guild_id, timestamp)` para relatórios. Hoje a tabela só recebe `INSERT`: nenhum código lê `fabricacoes_colete` (grep), então os dados são gravados e nunca usados.
7. **Gravar antes de apagar o print** e implementar `on_error` nas views `ColeteConfirmView`/`ColetePanelView` com feedback ao usuário.
8. **Testes:** cobrir o fluxo de confirmação (mock de `wait_for`), a concorrência de dupla confirmação, o parse de valor/quantidade da encomenda e a integração com o baú (estoque insuficiente → nada gravado).
9. **Higiene:** `core/config.py` faz `DATA_DIR.mkdir` e exige `DISCORD_TOKEN` no import, o que obriga a ter env até para teste unitário puro. Isolar a configuração por lazy-load ou usar `conftest.py` com env fake.

## Novas funções sugeridas
| Nome | O que faz | Esforço | Valor |
|---|---|---|---|
| **Fila de encomendas** (`/encomendas` + painel) | Lista paginada de pedidos por status (Pendente → Em produção → Entregue / Cancelada), com filtro por família e responsável. Botões "Assumir", "Marcar entregue" (liderança) e "Cancelar". | M | Alto: transforma o "post solto" em controle real de pedidos. |
| **Prazo + lembrete** | Campo "prazo" no modal e uma task (`tasks.loop`) que avisa o responsável/canal sobre encomendas vencendo ou atrasadas (🔴 badge). | P/M | Alto: evita pedido esquecido. |
| **Vínculo encomenda → fabricação → baú** | Na encomenda "Em produção", o botão "Fabricar" abre o fluxo do colete pré-preenchido com a quantidade. Isso dá baixa dos materiais no baú, dá entrada de "Colete", e o "Entregar" dá saída de "Colete" do baú. Tudo amarrado por `encomenda_id`/`operation_id`. | G | Muito alto: rastreabilidade ponta a ponta e estoque correto. |
| **Relatório de vendas/lucro** (`/relatorio_encomendas` ou embed semanal) | Por período: total vendido (R$), quantidade, custo de produção (materiais × preço de referência + custo fixo), lucro bruto, top famílias e top membros produtores. | M | Alto para a liderança. |
| **Ranking de fabricação** | Usa `fabricacoes_colete` (hoje nunca lido) para ranking semanal de quem mais fabricou, no mesmo padrão do ranking de farm. | P | Médio: engajamento, aproveita dados que já existem. |
| **Receitas genéricas de fabricação** | Generaliza o colete para N produtos (C4, Algema, Colete...) com receita configurável por guild: um select "Produto" e depois "Quantidade". | M/G | Médio/alto: reaproveita todo o fluxo. |
| **Verificação de saldo em tempo real** | Na confirmação, mostra o estoque do baú vs necessário e calcula "máx. fabricável agora". | P (depois da integração) | Alto: evita erro e retrabalho. |
| **Cancelar / desfazer fabricação** | Botão para a liderança no log da fabricação que estorna (`undo_items`) e marca o registro como revertido. | P/M | Médio: corrige erro humano sem mexer no DB na mão. |

## Top 3 ações recomendadas
1. **Corrigir a dupla contagem e integrar o colete ao baú de forma atômica.** Lock por usuário no fluxo de print (`colete.py:158-170`). Na confirmação, `apply_operation("saida", materiais, operation_id=...)` validando o saldo e depois entrada de "Colete". Gravar `bau_operation_id` em `fabricacoes_colete`, gravar antes de apagar o print e estornar em caso de falha.
2. **Persistir as encomendas com status e responsável.** Tabela `encomendas`, validação numérica de quantidade/valor e view persistente na mensagem ("Assumir" / "Marcar entregue" / "Cancelar", com checagem de cargo via `config/paineis.py`). Com isso a fila e o relatório de vendas/lucro passam a ser possíveis.
3. **Tornar o colete multi-servidor e padronizar o visual.** Adicionar "colete" ao dashboard (`SISTEMAS`) e remover `LOG_FABRICACAO_CHANNEL_ID` fixo (`colete.py:34`). Aplicar #FFD700, footer `Morro do Mineiro — Sistema de X`, acentos e moeda `R$` nos dois módulos. Guardar/apagar o painel antigo de encomenda.
