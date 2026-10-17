# Fase 5 — organização gradual de pastas

## Objetivo

Separar pontos de entrada de domínio, interface e persistência sem uma
migração ampla dos cogs ativos.

## Mudanças realizadas

- `features/set` e `features/acao` passaram a expor as APIs públicas dos
  domínios.
- `infrastructure/database.py` passou a ser a fachada de inicialização do
  banco usada pelo `main.py`.
- `infrastructure/repositories/set_requests.py` e
  `infrastructure/repositories/acoes.py` isolam chamadas de persistência para
  os serviços de Set e Ação.
- `ui/views/set.py` e `ui/views/acao.py` são superfícies de compatibilidade
  para as Views existentes; a implementação original não foi apagada nem
  duplicada.
- Entradas de Set e Ação que importavam Views de outros cogs passaram a usar
  as superfícies `ui.views.*`.

## Compatibilidade preservada

- Nenhum cog foi removido ou renomeado.
- Os imports antigos dos serviços continuam válidos.
- Comandos, mensagens, embeds, permissões e `custom_id` não foram alterados.
- O banco continua sendo SQLite local e usa as migrações existentes.
- Não houve movimentação física de módulos legados, evitando quebrar imports
  externos ainda não comprovados.

## Limitações conhecidas

O projeto ainda possui imports históricos entre cogs de Farm, Baú, Anúncio e
Hierarquia. Eles permanecem nesta etapa por dependerem de uma migração de cada
domínio e de validação dos fluxos ativos. As fachadas novas permitem migrar um
domínio por vez sem remover esses adaptadores.

## Validação da fase

- Testes: `222 passed, 1 warning, 12 subtests passed`.
- Sintaxe: `compileall` em `core`, `services`, `infrastructure`, `features`,
  `ui`, `cogs`, `main.py` e `tests`.
- Imports de camadas: Set, Ação, banco, repositórios e Views importados com
  sucesso.
- Extensões carregadas localmente: `31`.
- Comandos registrados localmente: `51`, todos únicos.
- Migrações criadas nesta fase: nenhuma.

## Próxima fase recomendada

Separar Farm e Baú por serviços e repositórios públicos, começando por
adaptadores de leitura e sem consolidar os JSONs do Baú automaticamente.
