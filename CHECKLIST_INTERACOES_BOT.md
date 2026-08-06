# Checklist de comandos, botoes, selects e modais do bot

Data de criacao: 2026-07-23

Use este checklist durante um teste real no Discord. A ideia e validar duas coisas ao mesmo tempo:

- A tela do Discord recebeu resposta em ate 3 segundos, ou mostrou que o bot esta processando.
- Os logs nao registraram `Unknown interaction`, `Interaction has already been acknowledged`, traceback, erro de permissao inesperado ou falha de envio.

## Preparacao

- [ ] Iniciar o bot sem erros no terminal.
- [ ] Confirmar no log que todos os cogs carregaram.
- [ ] Rodar `python -m pytest` antes do teste manual.
- [ ] Confirmar que `/ping` responde com latencia.
- [ ] Confirmar que `/status` responde e mostra uptime/servidores/dados.
- [ ] Confirmar que os comandos globais foram sincronizados no startup.
- [ ] Verificar que o bot tem permissoes de `Enviar mensagens`, `Usar comandos de aplicativo`, `Gerenciar mensagens`, `Gerenciar canais`, `Gerenciar cargos`, `Anexar arquivos` e `Ler historico`, conforme o modulo testado.
- [ ] Testar com usuario de lideranca.
- [ ] Testar com usuario permitido comum.
- [ ] Testar com usuario sem permissao.

Comando util apos cada bloco de testes:

```powershell
rg -n "ERROR|Traceback|Unknown interaction|already been acknowledged|InteractionResponded|NotFound|HTTPException" logs
```

## Fluxo critico: definir metas

Este e o fluxo que deve ser testado primeiro, por causa do erro visto de "bot nao respondeu a tempo".

- [ ] Usar `/config_ver` e confirmar que Farm tem cargos/canais configurados.
- [ ] Usar `/meta` com usuario sem lideranca; esperado: mensagem ephemeral negando permissao.
- [ ] Usar `/meta` com lideranca; esperado: painel ephemeral de metas aparece.
- [ ] Clicar `Definir Metas`; esperado: resposta ephemeral com escolha de tipo.
- [ ] Clicar `Kit Desmanche`; esperado: modal abre imediatamente.
- [ ] Enviar modal vazio; esperado: erro ephemeral pedindo pelo menos uma quantidade.
- [ ] Enviar quantidade negativa/letra; esperado: erro ephemeral de valor invalido.
- [ ] Enviar meta valida; esperado: confirmacao ephemeral.
- [ ] Clicar `Definir Metas` novamente.
- [ ] Clicar `Colete`; esperado: modal abre imediatamente.
- [ ] Enviar meta valida de colete; esperado: confirmacao ephemeral.
- [ ] Clicar `Definir Metas` novamente.
- [ ] Clicar `Dinheiro`; esperado: modal abre imediatamente.
- [ ] Enviar dinheiro vazio; esperado: erro ephemeral.
- [ ] Enviar dinheiro em formato `50000`; esperado: confirmacao.
- [ ] Enviar dinheiro em formato `R$ 50.000`; esperado: confirmacao.
- [ ] Depois de cada confirmacao, verificar se ranking/tickets/aviso de meta atualizada nao geraram erro no log.
- [ ] Clicar `Atualizar` no painel de metas; esperado: embed atualizado sem erro.
- [ ] Esperar mais de 120 segundos na tela de escolha do tipo e clicar um botao; esperado: sessao expirada ou nenhuma acao, sem traceback.
- [ ] Esperar mais de 15 minutos no painel de metas e clicar `Atualizar`; esperado: botao expirado ou sem acao, sem traceback.

Pontos de atencao no codigo:

- `DefinirMetasModal.on_submit` responde antes de atualizar ranking, tickets e avisos, o que reduz risco de timeout no submit.
- `EscolherTipoMetaView` abre modais com `_safe_send_modal`; se o modal nao abrir, verificar `logs/farm.log` para `Erro ao enviar modal`.
- O erro `Unknown interaction (10062)` normalmente indica resposta tardia ou interacao expirada.
- O erro `Interaction has already been acknowledged (40060)` indica tentativa de responder duas vezes pela API errada.

## Comandos base e setup

| OK | Comando | Cenario minimo |
| --- | --- | --- |
| [ ] | `/ping` | Responde ephemeral com latencia. |
| [ ] | `/status` | Responde ephemeral com status do bot. |
| [ ] | `/config_ver` | Mostra configuracao atual com usuario autorizado. |
| [ ] | `/setup_bot` | Salva canais/cargos e responde via followup. |
| [ ] | `/setup_farm` | Valida cargos de lideranca/permitidos e salva canais. |
| [ ] | `/setup_ausencia` | Salva canal de ausencias. |
| [ ] | `/setup_encomenda` | Salva canal de encomendas. |
| [ ] | `/setup_log_saida` | Salva canal de log de saida. |
| [ ] | `/setup_flanelinha` | Salva cargo Flanelinha. |
| [ ] | `/sincronizar_flanelinha` | Copia permissoes ou informa pre-requisito faltante. |
| [ ] | `/sincronizar_gerente_produtos` | Cria/sincroniza cargo ou informa pre-requisito faltante. |

## Farm, metas, ranking e resultados

| OK | Comando/interacao | Cenario minimo |
| --- | --- | --- |
| [ ] | `/meta` | Abre painel de metas para lideranca. |
| [ ] | `MetaView > Definir Metas` | Abre escolha Kit/Colete/Dinheiro. |
| [ ] | `EscolherTipoMetaView > Kit Desmanche` | Abre modal e salva meta valida. |
| [ ] | `EscolherTipoMetaView > Colete` | Abre modal e salva meta valida. |
| [ ] | `EscolherTipoMetaView > Dinheiro` | Abre modal e salva meta valida. |
| [ ] | `MetaView > Atualizar` | Atualiza embed. |
| [ ] | `/farm` | Usuario permitido recebe painel proprio. |
| [ ] | `FarmView > Abrir Ticket de Farm` | Abre ticket ou responde erro claro se sistema indisponivel. |
| [ ] | `FarmView > Atualizar` | Atualiza painel do usuario. |
| [ ] | `/resultado` | Lideranca ve painel de resultados. |
| [ ] | `ResultadoView > select membro` | Mostra detalhes do membro. |
| [ ] | `DetalheResultadoView > Aprovar Meta` | Aprova meta concluida. |
| [ ] | `DetalheResultadoView > Aprovar Antecipadamente` | Abre escolha de nivel. |
| [ ] | `AprovarNivelView > Elite` | Registra aprovacao antecipada elite. |
| [ ] | `AprovarNivelView > Meta Batida` | Registra aprovacao antecipada 100%. |
| [ ] | `AprovarNivelView > Parcial` | Registra aprovacao antecipada parcial. |
| [ ] | `DetalheResultadoView > Voltar` | Retorna ao painel de resultados. |
| [ ] | `/historico` | Consulta historico proprio. |
| [ ] | `/historico membro:<outro>` | Sem lideranca nega; com lideranca mostra historico. |
| [ ] | `/ranking` | Mostra ranking da semana atual. |
| [ ] | `/ranking semana:DD/MM/AAAA` | Mostra historico ou erro para semana futura. |

## Tickets de farm

| OK | Interacao | Cenario minimo |
| --- | --- | --- |
| [ ] | `FarmTicketView > Lancar Farm` | Abre modal de lancamento. |
| [ ] | `FarmTicketLaunchModal` | Valida numeros, comprovante e salva lancamento. |
| [ ] | `FarmTicketView > Ver Comprovantes` | Mostra comprovantes ou mensagem vazia controlada. |
| [ ] | `FarmTicketView > Recolhimento` | Abre modal/fluxo de recolhimento conforme meta. |
| [ ] | `FarmTicketView > Assumir Ticket` | Lideranca assume; usuario sem permissao recebe erro. |
| [ ] | `FarmTicketView > Revisar` | Abre acoes de revisao. |
| [ ] | `ReviewActionsView > Marcar problema` | Abre modal de motivo. |
| [ ] | `ReviewActionsView > Corrigir valores` | Abre modal de correcao. |
| [ ] | `ReviewActionsView > Resolver revisao` | Marca revisao como resolvida. |
| [ ] | `FarmTicketView > Aprovar Meta` | Aprova quando elegivel. |
| [ ] | `FarmTicketView > Finalizar Ticket` | Abre modal e finaliza. |
| [ ] | `ManualDeleteConfirmView > Confirmar exclusao` | Exclui quando permitido. |
| [ ] | `ManualDeleteConfirmView > Cancelar` | Cancela sem excluir. |
| [ ] | `AdminTicketListView > Anterior/Proxima` | Pagina lista sem travar. |

## Recolhimento

| OK | Comando/interacao | Cenario minimo |
| --- | --- | --- |
| [ ] | `/recolhimento` | Lideranca recebe escolha de tipo. |
| [ ] | `EscolherTipoView > Dinheiro Sujo` | Cria ciclo e posta embed. |
| [ ] | `EscolherTipoView > Farm` | Cria ciclo e posta embed. |
| [ ] | `RecolhimentoDinheiroView > Registrar` | Abre selecao de membro ou avisa que nao ha lancamentos. |
| [ ] | `RecolhimentoFarmView > Registrar` | Abre selecao de membro ou avisa que nao ha lancamentos. |
| [ ] | `RecolhimentoMembroSelectView > select` | Abre modal correto. |
| [ ] | `RecolhimentoMembroSelectView > Anterior/Proxima` | Pagina membros. |
| [ ] | `RecolhimentoDinheiroModal` | Valida dinheiro e atualiza embed. |
| [ ] | `RecolhimentoFarmModal` | Valida itens e atualiza embed. |
| [ ] | `RecolhimentoMetaModal` | Nao permite recolher acima do saldo. |
| [ ] | `PagamentoModal` | Marca ciclo como pago e atualiza embed. |

## Paineis principais

| OK | Comando/interacao | Cenario minimo |
| --- | --- | --- |
| [ ] | `/setup_painel_operacoes` | Posta painel de operacoes. |
| [ ] | `/setup_painel_set` | Posta painel de set. |
| [ ] | `/setup_dashboard` | Posta dashboard persistente. |
| [ ] | `Dashboard > SetConfigModal` | Salva configuracao de set. |
| [ ] | `Dashboard > FarmConfigModal` | Salva configuracao de farm. |
| [ ] | `Dashboard > AnuncioConfigModal` | Salva configuracao de anuncios. |
| [ ] | `Dashboard > FarmTicketsConfigModal` | Salva configuracao de tickets. |
| [ ] | `Dashboard > AcaoConfigModal` | Salva configuracao de acoes. |
| [ ] | `Dashboard > SystemConfigModal` | Salva configuracao geral. |

## Set e aprovacao

| OK | Comando/interacao | Cenario minimo |
| --- | --- | --- |
| [ ] | `/setup_set` | Posta painel de set. |
| [ ] | `SetPanelView > Fazer Set` | Abre `SetModal`. |
| [ ] | `SetModal` | Envia solicitacao para canal de aprovacao. |
| [ ] | `ApprovalView > Aprovar` | Aplica cargos, pasta/apelido e log. |
| [ ] | `ApprovalView > Reprovar` | Marca reprovado e loga. |
| [ ] | `ApprovalView` sem permissao | Responde erro ephemeral. |

## Acao

Observacao: `/acao` aparece duas vezes em `cogs/acao.py`; validar no startup se apenas um comando ficou sincronizado e se o comportamento e o esperado.

| OK | Comando/interacao | Cenario minimo |
| --- | --- | --- |
| [ ] | `/acao` | Abre escolha de tipo ou modal conforme fluxo ativo. |
| [ ] | `AcaoTipoView > Fuga` | Abre modal de configuracao. |
| [ ] | `AcaoTipoView > No Tiro` | Abre modal de configuracao. |
| [ ] | `IniciarAcaoModal` | Valida data/horario/valor e posta acao. |
| [ ] | `AcaoSelectView > select acao` | Abre painel de participantes. |
| [ ] | `AcaoParticipantesView > Entrar` | Adiciona participante ou avisa duplicado. |
| [ ] | `AcaoParticipantesView > Sair` | Remove participante ou avisa que nao estava inscrito. |
| [ ] | `AcaoParticipantesView > Adicionar membro` | Lideranca abre select paginado. |
| [ ] | `AdicionarMembroPaginadoView > select` | Adiciona membro e atualiza painel. |
| [ ] | `AdicionarMembroPaginadoView > Anterior/Proxima` | Pagina membros. |
| [ ] | `AcaoParticipantesView > Remover membro` | Lideranca abre select de inscritos. |
| [ ] | `RemoverMembroView > select` | Remove membro e atualiza painel. |
| [ ] | `AcaoParticipantesView > Finalizar acao` | Abre modal de finalizacao. |
| [ ] | `FinalizarAcaoModal` | Valida resultado/pagamento e finaliza. |
| [ ] | `/setup_acao_painel` | Posta painel persistente de acao. |
| [ ] | `AcaoPainelView > Iniciar acao` | Abre fluxo de inicio. |

## Outros modulos com modais e botoes

| OK | Modulo | Cenario minimo |
| --- | --- | --- |
| [ ] | Anuncio: `/setup_anuncio` | Salva canal/cargos. |
| [ ] | Anuncio: `/painel_anuncio` | Posta painel. |
| [ ] | Anuncio: `Novo Anuncio > AnuncioModal` | Publica anuncio com/sem arquivo. |
| [ ] | Ausencia: `/painel_ausencia` | Posta painel. |
| [ ] | Ausencia: `AusenciaPanelView > Registrar` | Abre modal e registra ausencia. |
| [ ] | Ausencia: `/ausencias` | Lista ausentes. |
| [ ] | Encomenda: `/setup_encomenda_painel` | Posta painel. |
| [ ] | Encomenda: `/encomenda` | Abre/registra encomenda. |
| [ ] | Encomenda: `EncomendaPainelView > Registrar` | Abre modal e posta registro. |
| [ ] | Advertencia: `/setup_adv_painel` | Posta painel. |
| [ ] | Advertencia: `/setup-adv` | Configura sistema. |
| [ ] | Advertencia: `/adv` | Abre fluxo de advertencia. |
| [ ] | Bau: `/bau_setup` | Posta/configura painel. |
| [ ] | Bau: `BauPainelView > entrada/saida` | Navega categorias, quantidades, envio e cancelamento. |
| [ ] | Bau: `UndoView` | Pagina e desfaz movimentos permitidos. |
| [ ] | Bau: `ClearConfirmView` | Confirma/cancela zerar bau. |
| [ ] | Bau gerentes: `/bau_gerentes_setup` | Posta painel. |
| [ ] | Bau gerentes: botoes/selects | Configuram/removem gerentes por slot. |
| [ ] | Colete: `/colete` | Abre fluxo de quantidade e confirmacao. |
| [ ] | Colete: `ColeteConfirmView` | Confirma/cancela e trata timeout de print. |
| [ ] | Disparo: `/painel_disparo` | Posta painel. |
| [ ] | Disparo: `BroadcastView` | Abre modal e confirma/exclui disparos. |
| [ ] | Farm advertencias: `/setup_farm_advertencias` | Configura cargos. |
| [ ] | Farm advertencias: `/setup_farm_advertencias_painel` | Posta painel. |
| [ ] | Farm advertencias: `/farm_ausencia` | Registra ausencia de farm. |
| [ ] | Farm advertencias: painel | Consultar, aplicar previa, remover e cancelar. |
| [ ] | Farm membro: `/farm_membro` | Lideranca consulta/edita membro. |
| [ ] | Farm painel: `/setup_farm_painel` | Posta painel legado/operacional. |
| [ ] | Relatorio farm: `/setup_relatorio_farm` | Posta/configura relatorio. |
| [ ] | Hierarquia: `/setup_hierarquia` | Posta painel; selects de cargos/membros funcionam. |
| [ ] | Moderacao: `/clear` | Apaga quantidade valida e responde. |
| [ ] | Moderacao: `/organizar_canais` | Executa ou informa falta de permissao. |
| [ ] | Parcerias: `/setup_parcerias` | Posta painel. |
| [ ] | Parcerias: registro/edicao/remocao | Modais, selects e confirmacoes funcionam. |
| [ ] | Radio: `/setup_radio_painel` | Posta painel. |
| [ ] | Radio: `RadioPainelView > Definir radio` | Abre modal e renomeia canal. |
| [ ] | Ranking painel: `/setup_ranking_painel` | Posta painel historico. |

## Criterios de aprovacao final

- [ ] Todos os comandos respondem em ate 3 segundos ou fazem defer.
- [ ] Todos os botoes/selects respondem em ate 3 segundos, abrem modal, editam mensagem ou enviam erro claro.
- [ ] Todos os modais validam entrada invalida sem traceback.
- [ ] Usuarios sem permissao recebem erro ephemeral.
- [ ] Views persistentes continuam funcionando apos reiniciar o bot.
- [ ] Views temporarias expiradas nao geram traceback.
- [ ] Operacoes lentas usam followup depois da primeira resposta.
- [ ] Nenhum log novo contem `Unknown interaction (10062)`.
- [ ] Nenhum log novo contem `Interaction has already been acknowledged (40060)`.
- [ ] Nenhum log novo contem traceback nao esperado.
- [ ] `python -m pytest` continua passando no final.

