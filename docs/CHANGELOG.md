# Changelog

## 08/06/2026 a 09/06/2026

Alteracoes finalizadas e validadas no estado atual do bot.

> Nao houve commit em 08/06/2026. Os 12 commits deste periodo foram
> registrados em 09/06/2026, entre 02:52 e 15:14. As alteracoes locais
> adicionais descritas abaixo tambem foram incluidas na validacao.

### Bau da Gerencia

- Reestruturado o sistema do bau com uma camada propria de regras e acesso ao
  banco de dados.
- Adicionada movimentacao multipla por categoria, com ate cinco produtos por
  pagina e envio direto ao concluir o preenchimento.
- Mantida a movimentacao individual dos produtos.
- Adicionados ao catalogo os materiais aluminio, cobre, borracha, plastico,
  ferro e tecido.
- Criada uma categoria exclusiva para Kit de Desmanche.
- Restaurado o formato classico dos logs, com um registro separado para cada
  produto movimentado.
- Adicionado o recurso para desfazer seletivamente a ultima movimentacao do
  proprio usuario, com paginacao para operacoes extensas.
- A zeragem completa do bau passou a exigir permissao de administrador e
  invalida confirmacoes antigas para evitar lancamentos posteriores indevidos.
- Implementadas protecoes contra operacoes duplicadas, retiradas concorrentes
  e estoque negativo.
- Preservada a compatibilidade com o historico e o estoque existentes durante
  a migracao da estrutura do banco.
- Reorganizados e compactados os controles do painel.
- Corrigida a compatibilidade do painel com Python 3.11.

### Fabricacao de Coletes

- O antigo painel de heroina foi substituido pelo painel de fabricacao de
  coletes.
- Adicionada selecao para fabricar de 1 a 10 coletes por operacao.
- O painel calcula automaticamente ferro, plastico, tecido, aluminio, borracha
  e o custo total da fabricacao.
- A fabricacao exige confirmacao e envio de uma imagem comprobatoria em ate
  tres minutos antes de ser registrada.
- Adicionados estados de cancelamento, expiracao, erro de imagem e confirmacao
  de sucesso.
- O registro da fabricacao passou a ser salvo por servidor e enviado ao canal
  de log com membro, quantidade, materiais, custo e imagem.
- Criada a nova estrutura de banco para fabricacoes de coletes e para a
  referencia do painel persistente.
- Simplificada a identificacao do membro no log de fabricacao.

### Datas e Historico

- Padronizadas entradas e exibicoes de data para `DD/MM/AAAA` e data/hora para
  `DD/MM/AAAA HH:MM`, usando o fuso horario configurado pelo bot.
- Adicionada validacao de datas em acoes, encomendas e pendencias da lideranca,
  com mensagens claras para formato ou datas invalidas.
- Atualizada a exibicao de datas nos sistemas de farm, ponto, membros,
  recolhimento e paineis relacionados.
- O ranking do farm agora permite consultar semanas anteriores por seletor,
  navegar em blocos de 20 semanas ou informar uma data especifica.
- Os comandos de ranking e historico do farm agora aceitam uma semana para
  consulta e bloqueiam datas futuras.
- Periodos semanais historicos sao exibidos de segunda-feira a domingo.

### Validacao

- 40 testes automatizados executados com sucesso em 09/06/2026.
- Cobertura validada para regras do bau, concorrencia, migracao, desfazer,
  zeragem administrativa, interface do bau, calculo de coletes, datas e
  navegacao do ranking historico.
- Todos os modulos de `cogs`, `core`, `services` e `tests` foram compilados sem
  erros pelo Python.

### Commits do Periodo

- `49cc4ed` Melhora painel do bau da gerencia
- `6d3701d` Corrige compatibilidade do bau com Python 3.11
- `a929df6` Organiza botoes do painel do bau
- `d32db50` Adiciona materiais ao bau da gerencia
- `1155a05` Separa kit de desmanche no bau
- `e41b6c5` Restaura movimentacao individual do bau
- `a47e996` Compacta botoes do painel do bau
- `2a3fc6a` Restaura layout classico dos logs do bau
- `a3c6df4` Adiciona lancamento multiplo por categoria
- `0cd2c3d` Restringe zeragem e envia lancamentos direto
- `f93207c` Substitui painel de heroina por coletes
- `be96f9b` Simplifica membro no log de coletes
