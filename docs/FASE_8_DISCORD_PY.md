# Fase 8 — atualização isolada do discord.py

## Objetivo

Atualizar a biblioteca Discord somente depois da estabilização dos fluxos,
validando a compatibilidade antes de qualquer mudança visual.

## Mudança realizada

- `requirements.txt`: `discord.py==2.3.2` → `discord.py==2.7.1`.
- Nenhum embed foi convertido para Container.
- Nenhum comando, permissão, mensagem ou `custom_id` foi alterado.
- Nenhum painel existente foi substituído ou republicado.

## Validação

Ambiente temporário separado, sem alterar a venv do projeto:

- Versão testada: `discord.py 2.7.1`.
- Testes: `227 passed, 11 warnings, 12 subtests passed`.
- Sintaxe: `compileall` completo.
- Imports e carregamento: `30` extensões, `50` comandos únicos.
- Views persistentes: registradas sem erro.
- Banco temporário: inicializado pelos testes.

Os avisos novos são depreciações de propriedades de UI usadas por testes e
código existentes (`discord.ui` recomenda `Label` em alguns casos). Eles não
impediram a execução e não foram tratados com uma migração visual ampla.

## Riscos restantes

- O teste local não conecta ao Discord real nem valida a sincronização global
  de comandos.
- A atualização precisa de uma janela de validação no servidor antes de
  qualquer deploy; deploy está fora do escopo desta execução.
- Containers não foram adotados nesta fase.

## Próxima fase recomendada

Validar manualmente os painéis críticos em ambiente controlado e, somente
depois, considerar novos painéis separados usando Containers, começando pelo
Set canônico comprovado em uso.
