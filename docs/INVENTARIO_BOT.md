# Inventário técnico do bot

Data do inventário: 17/10/2026

Este inventário foi obtido por busca no código da branch
`refactor/organizar-estabilizar-bot`. IDs e painéis abaixo são referências
encontradas no repositório; não foram confirmados contra um servidor Discord
durante a auditoria local.

## Extensões carregadas

`core/extensions.py` carrega atualmente:

`cogs.setup`, `cogs.sistema`, `cogs.membros`, `cogs.apelidos`,
`cogs.setup_set`, `cogs.farm`, `cogs.ausencia`, `cogs.acao`, `cogs.anuncio`,
`cogs.encomenda`, `cogs.paineis`, `cogs.setup_paineis`, `cogs.lideranca`,
`cogs.setup_lideranca`, `cogs.adv`, `cogs.colete`, `cogs.dashboard`,
`cogs.farm_painel`, `cogs.farm_tickets`, `cogs.farm_relatorio`,
`cogs.farm_advertencias`, `cogs.ranking_painel`, `cogs.parcerias`,
`cogs.hierarquia`, `cogs.acao_painel`, `cogs.radio`, `cogs.bau`, `cogs.mod`,
`cogs.recolhimento`, `cogs.bau_gerentes` e `cogs.disparo`.

Módulos de apoio que não são extensões: `cogs.set_views`, `cogs.bau_core`,
`cogs.farm_embeds` e `services/*`.

## Comandos slash encontrados

- Sistema/configuração: `/ping`, `/status`, `/setup_bot`, `/setup_farm`,
  `/setup_ausencia`, `/setup_encomenda`, `/setup_log_saida`,
  `/setup_anuncio`, `/config_ver`, `/encomenda`, `/setup_set`,
  `/setup_painel_operacoes`, `/setup_painel_set`, `/setup_dashboard`,
  `/setup_lideranca`, `/setup_adv`, `/setup_adv_painel`, `/setup_colete`,
  `/setup_farm_painel`, `/setup_acao_painel`, `/setup_hierarquia`,
  `/setup_radio_painel`, `/setup_ranking_painel`, `/setup_relatorio_farm`,
  `/setup_parcerias`, `/setup_bau`, `/setup_bau_gerentes`,
  `/setup_painel_disparo`.
- Farm: `/meta`, `/farm`, `/resultado`, `/historico`, `/ranking`,
  `/definir_metas`, `/lancar`, `/editar`, `/aprovar_farm`, `/avisos_farm`,
  `/farm_membro`, `/farm_ausencia`, `/setup_farm_advertencias`,
  `/setup_farm_advertencias_painel`.
- Ação: `/acao` (há duas definições textuais no módulo, mas a classe final
  `AcaoCog` é a que permanece registrada), além dos botões e modais do fluxo.
- Operação: `/ausencias`, `/adv`, `/colete`, `/recolhimento`, `/clear`,
  `/organizar_canais`, `/radio`, `/bau`, `/bau_gerentes`, `/parcerias` e
  comandos de anúncios, encomendas, liderança, ranking e disparo existentes
  nos cogs correspondentes.

O conjunto exato registrado deve continuar sendo validado com uma instância
do bot sem conexão ao Discord; o inventário acima é a leitura estática atual.

## Views persistentes e custom_id

Views persistentes (`timeout=None`) encontradas:

- Set: `SetPanelView` (`set_panel:fazer_set`) e `ApprovalView`
  (`approval:aprovar`, `approval:reprovar`).
- Painéis: `PainelOperacoesView`, `PainelSetView`
  (`painel_set:pedir`) e painel legado de Farm.
- Farm/tickets: `FarmTicketView`, painel de advertências, relatório pendente,
  painel de hierarquia, painel de ação, painel de encomendas, painel de
  ausência, painel de anúncio, painel de rádio e painéis de recolhimento.
- Baú e demais painéis têm custom IDs documentados diretamente nos módulos;
  nenhum foi removido nesta fase.

IDs críticos preservados e caracterizados nos testes: `set_panel:fazer_set`,
`approval:aprovar`, `approval:reprovar`, `painel_set:pedir`,
`acao:entrar`, `acao:sair`, `acao:adicionar`, `acao:remover` e
`acao:encerrar`.

## Persistência e fontes de configuração

- Banco principal: `data/farm.db`, definido por `ARQUIVO_BANCO_FARM`.
- Banco separado do Baú: `bau.db`, usado por `cogs.bau` e `cogs.bau_core`.
- JSONs versionados em `data/`: `autoroles_config.json` e
  `commands_config.json`.
- JSONs legados/operacionais referenciados: `channel_map.json`,
  `ausencias.json`, `bau_painel.json`, `bau_gerentes_painel.json` e
  `data/broadcast_messages.json`. A busca local não confirmou todos os
  arquivos presentes no checkout atual.
- Configuração por guild: tabelas `guild_config` e `system_config`.
- Variáveis de ambiente: token, application ID, banco, fuso e dois canais
  globais legados (`CANAL_LOG_ENTRADA_ID` e `CANAL_LOG_PD_ID`).

Tabelas que sustentam os fluxos críticos: `guild_config`, `system_config`,
`acoes`, `acao_participantes`, `farm_tickets`, `farm_ticket_lancamentos`,
`channel_map`, `ausencias`, `recolhimento_ciclos` e `recolhimento_entregas`.

## IDs fixos encontrados no código

Os itens abaixo continuam fixos e devem ser migrados somente com confirmação
de uso e fallback compatível:

- Logs legados: `1474869321187459143`, `1496346120111259743`.
- Set: cargo fallback `1474869320659107853`; cargo de sincronização de pastas
  `1474869320684146841`.
- Baú: canal `1474869322387292357`, log `1499589255784173678`.
- Baú gerentes: canal `1502107652027715705`.
- Disparo: categoria `1474869322387292362`.
- Rádio: canal `1474869321863008296`.
- Ranking: categoria `1504287738298372216`.
- Farm: canal de avisos de meta `1474869321506488447`.
- Colete: canal de log de fabricação `1506880362633236630`.
- Liderança: canal padrão do painel `1506885629181689886`.
- Hierarquia: cargos autorizados `1474869320684146847`,
  `1474869320684146846` e `1490821840191619322`.
- Atualização de preços: canal de referência `1474869322139566167` em
  `scripts/atualizar_precos.py`.
- Dashboard: canal `1494692392052461588`; os IDs de exemplo
  `111222333444555` e `666777888999000` aparecem como valores de fallback/teste
  no código e não foram tratados como IDs reais.

Nenhum desses valores foi alterado na Fase 1.

## Dúvidas que exigem confirmação no servidor

1. Qual dos dois painéis de Set é o painel canônico atualmente usado pelos
   membros: `SetPanelView` (`set_panel:fazer_set`) ou `PainelSetView`
   (`painel_set:pedir`).
2. Se o dashboard ainda tem mensagens ativas, apesar de o diagnóstico indicar
   que não está em uso.
3. Se os painéis antigos de Baú e Disparo ainda existem em canais ativos.
4. Se os IDs fixos acima são válidos em todas as guilds configuradas.

Enquanto essas dúvidas não forem confirmadas, os fluxos atuais e os fallbacks
permanecem preservados.
