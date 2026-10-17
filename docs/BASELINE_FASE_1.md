# Baseline da Fase 1

Data: 17/10/2026

- Branch inicial: `backup/pre-github-sync-20261007-morro-bot-current`.
- Branch de trabalho criada: `refactor/organizar-estabilizar-bot`.
- Alteração não relacionada preservada: `.vscode/` permanece não rastreada.
- Commit inicial: `18e09eb` (`Preenche recolhimento com saldo disponivel`).
- Deploy/merge/produção: nenhum.

## Ambiente de teste

O `venv` do projeto apontava para uma instalação removida de Python 3.12.10.
Foi instalado Python 3.12 no escopo do usuário e criado um ambiente temporário
fora do repositório em:

`C:\Users\Samuel\AppData\Local\Temp\morro-mineiro-bot-test-20261017`

Dependências instaladas nesse ambiente: `requirements.txt` e `pytest`.

## Resultado inicial

Com o código antes das alterações da Fase 1:

`206 passed, 1 warning, 12 subtests passed in 6.28s`

O warning é o `DeprecationWarning` de `audioop` emitido pelo
`discord.py 2.3.2` no Python 3.12. Nenhum teste falhou.
