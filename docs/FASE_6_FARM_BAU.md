# Fase 6 — Farm, Baú e armazenamento

## Objetivo

Reduzir acoplamento e tornar explícitos os pontos de persistência sem alterar
regras operacionais ou migrar dados automaticamente.

## Farm

- Criada a API pública `services.farm_service.farm_service`, que encapsula as
  operações atuais de metas, progresso, lançamentos, aprovação e relatórios.
- `cogs/farm.py` usa aliases temporários apontando para essa API, preservando o
  corpo e as mensagens do cog durante a transição.
- O catálogo `MATERIAIS_POR_COLETE` foi centralizado em
  `features/farm/catalog.py`; `cogs.colete` continua exportando o mesmo nome
  para compatibilidade.
- Builders de embeds passaram a ter a superfície `ui.messages.farm`.
- Imports de modais e Views de Farm vindos de outros cogs passaram para
  `ui.views.farm`.

## Baú

O inventário atual foi confirmado localmente:

| Recurso | Local | Estado observado |
| --- | --- | --- |
| Banco principal | `bau.db` | 84 produtos, 0 históricos, 0 operações, 1 meta e 10 slots de gerentes |
| Painel principal | `bau_painel.json` | arquivo ausente nesta cópia local |
| Painel de gerentes | `bau_gerentes_painel.json` | arquivo ausente nesta cópia local |
| Código de regra/persistência | `cogs/bau_core.py` | preservado; testes existentes continuam usando-o |

Foi criada `services.bau_service` com caminhos explícitos, leitura/gravação
compatível dos dois JSONs e o repositório atual. `cogs.bau` e
`cogs.bau_gerentes` passaram a usar esse serviço; `cogs.colete` deixou de
importar o repositório pelo cog `cogs.bau`.

Nenhum dado foi migrado, sobrescrito ou apagado. O banco local e os JSONs
continuam fora do versionamento conforme o `.gitignore`. A consolidação futura
deverá criar backup, validar a leitura dos dois painéis e só então adotar uma
estrutura única.

## Compatibilidade preservada

- Comandos e mensagens de Farm, Baú e Colete não foram alterados.
- `cogs.bau.repo`, `cogs.bau.DB_PATH`, `cogs.bau.PAINEL_JSON` e os símbolos
  públicos antigos continuam disponíveis.
- `cogs.colete.MATERIAIS_POR_COLETE` e os imports de `cogs.bau_core` continuam
  válidos.
- IDs de canais passaram a usar o inventário centralizado de configurações,
  mantendo os valores legados.

## Validação da fase

- Testes: `226 passed, 1 warning, 12 subtests passed`.
- Sintaxe: `compileall` dos diretórios ativos.
- Banco temporário: Farm e Baú exercitados em diretórios temporários.
- Imports: serviços, repositórios e adaptadores importados com sucesso.
- Migrações criadas nesta fase: nenhuma.
- Não houve migração automática de banco/JSON.

## Riscos restantes

- `cogs/bau_core.py` ainda é a implementação física do repositório para
  preservar imports históricos.
- `services/db_service.py` ainda concentra funções de vários domínios.
- A validação não acessa Discord nem o banco de produção.

## Próxima fase recomendada

Confirmar por busca de dependências o uso do dashboard e removê-lo apenas da
lista de extensões carregadas, mantendo o código no histórico.
