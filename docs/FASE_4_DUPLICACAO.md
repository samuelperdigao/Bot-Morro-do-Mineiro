# Fase 4 — duplicação de Set e Ação

## Objetivo

Centralizar as regras de negócio de Set e Ação sem remover entradas antigas,
alterar mensagens existentes ou trocar os `custom_id` ativos.

## Mapeamento dos painéis de Set

| Entrada | Interface | `custom_id` | Persistência do painel | Diferença observada |
| --- | --- | --- | --- | --- |
| `/setup_set` | `cogs.set_views.SetPanelView` | `set_panel:fazer_set` | Não grava referência do painel | Embed simples e fluxo legado |
| `/setup_painel_set` | `services.paineis_service.PainelSetView` | `painel_set:pedir` | Grava `painel_set_channel_id` e `painel_set_message_id` | Embed configurado, logo e registro de painel |

Não há evidência local suficiente para declarar qual painel é o canônico em
produção. Os dois comandos permanecem registrados e os dois `custom_id` foram
preservados. Ambos agora encaminham a solicitação para o mesmo `SetRequestService`
por meio de `SetModal`.

## Serviços introduzidos

- `services/set_requests.py`: ciclo de vida persistente de uma solicitação de
  Set — criação, associação da mensagem, recuperação, claim, conclusão e
  liberação após erro.
- `services/acao_service.py`: criação, leitura, participantes, entrada,
  remoção e finalização atômica de Ação. A API retorna motivos explícitos para
  duplicidade, limite de vagas e ação encerrada.

As Views continuam responsáveis por Discord, respostas e edição dos painéis.
Os cogs não acessam mais diretamente as operações de persistência do fluxo
ativo de Ação; o Set usa o serviço tanto no modal quanto na recuperação.

## Compatibilidade preservada

- Comandos `/setup_set`, `/setup_painel_set` e `/acao` mantidos.
- `set_panel:fazer_set`, `painel_set:pedir`, `approval:aprovar`,
  `approval:reprovar` e os `custom_id` de Ação mantidos.
- Mensagens, embeds e painéis já enviados não são editados automaticamente.
- O bloco textual legado duplicado em `cogs/acao.py` não foi apagado nesta
  fase. A classe ativa já utiliza o serviço; a remoção do legado exige uma
  validação adicional de histórico e execução no servidor.

## Validação da fase

- Testes: `222 passed, 1 warning, 12 subtests passed`.
- Sintaxe: `compileall` de `core`, `services`, `cogs`, `main.py` e `tests`.
- Imports: módulos de Set, Ação e serviços importados com sucesso.
- Inicialização do banco: executada em banco local/temporário pelos testes e
  na verificação de carregamento.
- Extensões carregadas localmente: `31`.
- Comandos registrados localmente: `51`, todos únicos.
- `custom_id` legados: cobertos pelos testes de caracterização existentes.
- Migrações criadas nesta fase: nenhuma.

## Riscos restantes

- O painel canônico de Set ainda depende de evidência real de uso no servidor.
- Ação ainda contém um bloco legado não removido; ele não é usado pela classe
  final registrada, mas permanece para evitar exclusão prematura.
- A validação não acessa Discord nem banco de produção.

## Próxima fase recomendada

Iniciar a organização gradual de pastas, começando por Set e Ação, mantendo
adaptadores para imports antigos e sem mover Farm, Baú ou dashboard em lote.
