# Auditoria do Bot Morro do Mineiro — Compilado

Data: 09/11/2026 · Base: commit `5e70f12` · Método: 15 agentes, um por domínio funcional. Cada agente só leu o código, sem alterar nada, usando como critério a skill `engineering:code-review` (o agente de infra usou também a `engineering:tech-debt`).

Os relatórios completos, com `arquivo:linha`, trecho do código e correção sugerida, estão nos arquivos `01_*.md` a `15_*.md` desta pasta. Itens marcados como **SUSPEITA** nos relatórios não foram confirmados e precisam ser validados antes de mexer no código.

---

## Decisão: bot de servidor único

O bot atende **apenas o servidor do Morro do Mineiro**. IDs fixos no código são intencionais e não são bug. Com isso, ficam descartados o C10 (Ponto), o C11 (Dashboard), o vazamento do log de membros entre servidores, o `guild_id` do baú, o `/status` somando servidores, o painel global do Cache e toda a Onda 3 de multi-servidor. A padronização visual continua válida.

## Status

**Sessão 1 (Onda 1): concluída.**

| Item | Situação |
|---|---|
| C1 Backup do banco | ✅ Backup diário às 04:00, `/backup_agora`, backup antes de cada deploy |
| C1 Deploy seguro | ✅ Release via `git archive`, rollback automático, workflow do GitHub Actions |
| C2 Hierarquia | ✅ Só atribui cargos abaixo do próprio nível; troca atômica |
| C3 Disparo | ✅ Restrito à liderança, com log |
| Slots de gerente do baú | ✅ Restritos à liderança |
| C4 Baú por categoria | ✅ Navegação pela view, sem modal encadeado |
| C5 e C6 Farm | ✅ Lembretes corrigidos, parser de R$ estrito, edição sem multiplicar |
| Tratamento global de erros | ✅ Handlers globais, tasks que se reiniciam, sync protegido |

Próximo passo é a **Sessão 2**: Recolhimento (C9 e parser de R$), atualização do discord.py, estado persistente de Set e Ação (C7 e C8) e embeds paginados.

---

## 1. Placar geral

| # | Função | Nota | Críticas | Altas | Pior problema |
|---|---|:-:|:-:|:-:|---|
| 01 | Set (aprovação) | 5 | 1 | 3 | Aprovar/Reprovar quebram a cada restart |
| 02 | Farm | 5 | 2 | 3 | Lembretes de quarta e sábado morrem; editar multiplica o valor por 10 |
| 03 | Ranking | 6 | 0 | 2 | Painel some ou fica velho; empate muda a cada restart |
| 04 | Ação / Missões | 4 | 2 | 2 | Inscritos perdidos no restart; duas ações abertas colidem |
| 05 | Ausência | 5 | 0 | 1 | Fuso UTC; a task de hora em hora morre; lista estoura |
| 06 | Baú da Gerência | 5 | 1 | 2 | Lançamento por categoria quebrado em 8 de 13 categorias |
| 07 | Recolhimento | 5 | 1 | 3 | Embed congela após cerca de 7 entregas; `1500.50` vira 150.050 |
| 08 | Ponto | 5 | 1 | 2 | IDs fixos (só funciona no servidor original); ranking estoura |
| 09 | Liderança / Hierarquia | 4 | 1 | 2 | Um "\| 03" consegue se promover a Dono |
| 10 | Advertência / Mod / Membros | 4 | 0 | 4 | Advertência não fica salva; log de entrada e saída vaza entre servidores |
| 11 | Anúncio / Rádio / Disparo | 5 | 2 | 2 | Qualquer membro usa o Disparo |
| 12 | Encomenda / Colete | 4,5 | 0 | 4 | Um print conta como várias fabricações; o colete não baixa estoque do baú |
| 13 | Dashboard / Setup / Painéis | 4 | 1 | 4 | Dashboard preso a um canal fixo de um servidor |
| 14 | Cache FiveM / Sistema | 6,5 | 0 | 0 | Painel global; `/status` soma dados de todos os servidores |
| 15 | Infra / Arquitetura | 5 | 1 | 6 | Sem backup do `farm.db`; o deploy envia `.env` e a chave SSH |

**Total: 14 críticas e 40 altas.** Nenhuma função passa de 6,5.

---

## 2. Diagnóstico: 5 causas raiz explicam a maioria dos bugs

1. **O estado dos botões fica em memória.** Views sem `add_view`, ou com estado no `__init__`, morrem a cada deploy. Afeta Set (Aprovar/Reprovar), Ação (inscritos) e Hierarquia (custom_id fixo em view efêmera). A correção é guardar o estado no SQLite e recuperá-lo pelo `message_id` ou com `DynamicItem`, que exige discord.py 2.4+.
2. **IDs fixos no código num bot que se diz multi-servidor.** Ponto, Rádio, Disparo, Dashboard, Cache FiveM, Colete (log), Set (cargo "Pedir Set"), Farm (canal de avisos), Membros (log de entrada e saída) e Hierarquia. Há também tabelas sem `guild_id`: o baú inteiro. Em outro servidor essas funções quebram ou, pior, **gravam e postam no servidor do Morro**.
3. **Permissão ausente ou só por nome de cargo.** Disparo não checa nada. Os slots de gerente do baú também não. A hierarquia não compara níveis. A advertência aceita advertir a si mesmo, bots ou cargos acima.
4. **Tasks agendadas sem tratamento de erro e sem recuperação.** Valem para Farm, Ranking de domingo, Recolhimento, Ausência e Ponto. Uma exceção derruba a task até o próximo restart. Se o bot estiver fora do ar no minuto exato (domingo 23:59), o evento se perde para sempre.
5. **Limites do Discord sem tratamento.** Field de 1024 caracteres (Recolhimento, Ponto, Ação, Farm `/historico`), 25 fields (Ausência), 25 opções de select (Ação, aprovação do Farm), título de 256 (Anúncio) e modal aberto em resposta a outro modal (Baú). Funciona com poucos membros e quebra quando o servidor cresce.

Corrigir essas 5 causas com **helpers centrais** (state store de views, `guild_config` para todos os IDs, checagem de permissão por nível, decorator de task segura, paginação e divisão de embeds) resolve cerca de 60% da lista sem precisar mexer função por função.

---

## 3. Lista de críticas (corrigir primeiro)

| # | Função | Onde | Problema | Correção |
|---|---|---|---|---|
| C1 | Infra | `scripts/deploy.ps1:22-23` | Não há backup do `farm.db`. O deploy envia `.env`, `scripts/oracle.key` e `data/*.json` para produção e ignora falha de `scp`/`pip` | Backup diário com `sqlite3.backup()` e cópia fora da VM; deploy com lista fixa de pastas e `exit 1` em qualquer erro; apagar a `oracle.key` do servidor |
| C2 | Hierarquia | `cogs/hierarquia.py:43-125` | Escalonamento de privilégio: qualquer cargo autorizado aplica qualquer cargo, inclusive Dono | Só cargos abaixo do nível de quem executa; bloquear o próprio executor, o dono do servidor e bots |
| C3 | Disparo | `cogs/disparo.py:454-515` | Comando e botões sem permissão; qualquer membro dispara para todas as pastas ou apaga o último disparo | `default_permissions` + `interaction_check` + `send_log("disparo")` |
| C4 | Baú | `cogs/bau.py:376-379` | `send_modal` dentro do `on_submit` de outro modal. O Discord recusa, e 68 dos 84 produtos não conseguem ser lançados por categoria | Responder com `edit_message` mostrando a view com o botão "Próxima página" |
| C5 | Farm | `cogs/farm.py:1195,1246` | `row.get()` em `sqlite3.Row` gera `AttributeError` e mata as tasks de lembrete de quarta e sábado | `row["aprovacao_antecipada"]` + `@task.error` |
| C6 | Farm | `cogs/farm.py:43-46,550` | Editar um lançamento em dinheiro e só confirmar multiplica o valor por 10 (`"50000.0"` vira 500000) | Parser BRL estrito; default formatado como inteiro |
| C7 | Set | `cogs/set_views.py:139`, `main.py:30` | `ApprovalView` não é persistente: todo pedido pendente quebra no deploy | Tabela `set_requests` + `DynamicItem` |
| C8 | Ação | `cogs/acao.py:98-109` | Inscritos só em memória; duas ações abertas compartilham `custom_id` e uma sobrescreve a outra | Tabela de ações + view persistente única, com estado buscado pelo `message_id` |
| C9 | Recolhimento | `cogs/recolhimento.py:150-208` | Field passa de 1024 caracteres, a edição falha em silêncio e o TOTAL público fica errado | Dividir em vários fields ou botão de histórico; valores em centavos |
| C10 | Ponto | `cogs/ponto.py:29-30` | Categorias fixas no código: o `/setup_ponto` falha em qualquer outro servidor | Receber as categorias como parâmetros do setup (a tabela `ponto_config` já tem as colunas) |
| C11 | Dashboard | `cogs/dashboard.py:45,671-687` | Canal fixo: um admin de outro servidor posta e grava a config do servidor do Morro | `/config` efêmero, por servidor |

As demais 3 críticas são variações destas (Disparo, Farm e Ação têm duas cada). Detalhes nos relatórios.

---

## 4. Roadmap recomendado

### Onda 1 — Parar de quebrar (1 a 2 semanas) · obrigatória
1. **Backup do DB e deploy seguro** (C1). Esforço pequeno e o maior risco do projeto: perder o `farm.db` hoje significa perder tudo.
2. **Furos de permissão:** Hierarquia (C2), Disparo (C3), slots de gerente do baú, `/postar_cache_fivem` sem `guild_only`, Anúncio com @everyone liberado para qualquer anunciante.
3. **Bugs de 1 linha com impacto alto:** C5 (`row.get`), C6 (edição ×10), parser de dinheiro no Farm e no Recolhimento (`inf`, `nan`, `1500.50`), `round(latency)` com `inf` no `/ping`.
4. **Error handler global** (`tree.on_error`, `on_error`, `.error` em todas as tasks) mandando erros para um canal de ops. Também: não rodar `tree.sync()` se algum cog falhou ao carregar, porque hoje isso apaga os comandos daquele cog em todos os servidores.
5. **Baú por categoria** (C4) e o teste de UI que use banco de teste em vez do `bau.db` real.

### Onda 2 — Sobreviver a restart e crescer (2 a 4 semanas)
1. **Subir o discord.py de 2.3.2 para 2.6+.** Isso libera `DynamicItem` e Components V2 nativos. Junto, resolver a versão do Python: o `audioop-lts` não tem pacote para 3.11.
2. **State store para views:** Set (C7), Ação (C8), Encomenda (status, responsável) e Advertência (tabela `advertencias` com expiração e cargo).
3. **Tasks resilientes:** checar `semana_fim <= hoje` e recuperar no startup (Ranking de domingo, Recolhimento), auto-fechamento de ponto esquecido, snapshot semanal do ranking.
4. **Embeds paginados ou divididos** em todo lugar que lista membros (Recolhimento C9, Ponto, Ausência, Ação, Farm `/historico`, pendências da Liderança).
5. **`services/farm_service.py`:** a lógica de farm está triplicada em `farm.py`, `farm_painel.py` e `paineis.py`, com permissões divergentes.

### Onda 3 — Multi-servidor de verdade e funções novas
Só vale fazer se o bot for, de fato, para outros servidores. Se ele for usado só no Morro, **adiar o multi-servidor** e assumir explicitamente que é single-guild elimina metade do retrabalho. Decida isso antes da Onda 3.

1. Mover todos os IDs fixos para `guild_config` (C10, C11, Rádio, Disparo, Colete, Membros, Cache) e adicionar `guild_id` no baú.
2. `/config` por servidor com status ✅/⚠️/❌, `ChannelSelect`/`RoleSelect` e diagnóstico de saúde.
3. Padronizar o visual: #FFD700 e o footer "Morro do Mineiro — Sistema de X". Ausência, Liderança, Colete, Ponto, Recolhimento, Sistema e Encomenda estão fora do padrão, com cores azul, laranja e `0xF0A500`, acentos faltando e moeda em `$` em vez de R$.

---

## 5. Funções novas com melhor custo-benefício

Selecionadas entre cerca de 100 sugestões dos agentes. O critério foi valor alto para a facção e reaproveitamento de dados que já existem.

| Função | O que faz | Esforço | Depende de |
|---|---|:-:|---|
| **/perfil do membro** | Ficha única: farm, ponto, advertências, ausências, recolhimento, cargo e data de entrada | M | Advertência salva no banco (Onda 2) |
| **Ausência isenta a cobrança** | Farm e Recolhimento não cobram quem está ausente; cargo "Ausente" automático e botão "Voltei" | P | — |
| **Colete dá baixa no baú** | Fabricar desconta ferro, plástico e demais materiais, e dá entrada do colete via `apply_operation` (atômico, já existe) | P | — |
| **Advertência com acúmulo** | 3 advertências ativas geram punição configurável; expiração automática; revogação com motivo | M | Tabela `advertencias` |
| **Resultado da ação + lembrete** | Vitória, derrota e loot registrados; lembrete 15 minutos antes; histórico de presença por membro | M | Ação salva no banco |
| **Requisitos de promoção** | A hierarquia mostra se o membro cumpre meta de farm, horas de ponto e zero advertências | M | /perfil |
| **Status do servidor FiveM** | Jogadores online (via `/players.json`) e alerta de queda e volta | P | — |
| **Fila de encomendas** | Status pendente/assumida/entregue, responsável, prazo, relatório de vendas e lucro | M | Tabela `encomendas` |
| **Alerta de estoque baixo + relatório semanal do baú** | Aviso no canal da gerência; movimentação por gerente | P | Datas em ISO no baú |
| **Ranking com histórico** | Comparativo com a semana anterior, sequência de semanas com meta batida, ranking mensal | M | Snapshot do ranking |

---

## 6. Alerta de alocação

São 54 itens críticos ou altos e cerca de 100 ideias de funções novas. **Não tente fazer tudo junto.** Recomendação:

- **Faça a Onda 1 inteira antes de qualquer função nova.** Hoje há perda de dados possível (sem backup), um furo de privilégio (Hierarquia, Disparo) e funções que já estão quebradas em produção (Baú por categoria, lembretes do Farm).
- **Decida já se o bot é multi-servidor ou single-guild.** Essa decisão define se a Onda 3 existe.
- Das funções novas, comece pelas três de esforço P e valor alto: **Ausência isenta a cobrança, Colete dá baixa no baú e Status do FiveM.**

Os três itens marcados como esforço P podem ser feitos em paralelo à Onda 2, porque não dependem dela.
