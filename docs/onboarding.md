# Onboarding local

## Pré-requisitos

- Windows com PowerShell ou ambiente equivalente.
- Python 3.12, versão usada no CI e na validação local atual.
- Acesso autorizado a uma aplicação Discord apenas para execução manual; os
  testes automatizados não precisam de token.

Não copie `.env`, `oracle.key`, bancos ou logs para commits, prompts, tickets
ou relatórios.

## Preparar o ambiente

Na raiz do projeto:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

O projeto usa `requirements.txt` como manifesto atual. Não há `pyproject.toml`,
lockfile de dependências de desenvolvimento ou configuração de lint/type-check
versionada.

## Configuração local

Crie ou forneça um `.env` local com, no mínimo, `DISCORD_TOKEN` e
`APPLICATION_ID`. As demais variáveis e seus padrões estão descritos no
`README.md` e são lidas por `core/config.py`.

Os intents privilegiados **Server Members** e **Message Content** precisam ser
habilitados no Discord Developer Portal para uma execução real.

## Executar o bot

```powershell
.\venv\Scripts\python.exe main.py
```

Esse comando conecta ao Discord, sincroniza comandos e pode alterar mensagens,
canais, cargos ou configurações conforme o fluxo utilizado. Não use para
diagnóstico documental nem em um servidor não autorizado.

## Executar testes

```powershell
.\venv\Scripts\python.exe -m pytest tests/ -q
```

Os testes usam principalmente SQLite temporário, mocks e objetos reais de
views. Eles não substituem o teste manual em `docs/CHECKLIST_INTERACOES.md`.

## Primeiro diagnóstico seguro

```powershell
git status --short --branch
rg --files -g '!.git/**' -g '!**/venv/**' -g '!**/.codex-test-venv/**'
.\venv\Scripts\python.exe -m pytest tests/ -q
```

Para revisar logs já existentes sem acessar produção:

```powershell
rg -n "ERROR|Traceback|Unknown interaction|already been acknowledged|InteractionResponded|NotFound|HTTPException" logs
```

Não execute `scripts/deploy.ps1`, `scripts/atualizar_token.ps1`,
`scripts/atualizar_precos.py`, SSH ou comandos remotos como parte desse
diagnóstico.

## Operações de produção

Deploy, rollback, SSH, alteração de token, exclusão, ACL e `git push` exigem
confirmação específica. Os scripts SSH também exigem que a host key já esteja
validada no `known_hosts` padrão ou no arquivo indicado por
`MORRO_BOT_KNOWN_HOSTS`. Consulte `docs/operations-security.md` antes de
qualquer operação externa.

## Ordem recomendada para uma tarefa

1. Ler `AGENTS.md`, `PRODUCT.md`, este arquivo e a documentação do domínio.
2. Inspecionar o código e o estado do Git.
3. Definir aceitação e comandos de validação antes de implementar.
4. Alterar um domínio por vez, preservando contratos e dados.
5. Executar os testes relevantes e revisar o diff.
6. Atualizar a documentação responsável.
7. Fazer validação manual no Discord somente com autorização e ambiente
   controlado.
