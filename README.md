# Morro do Mineiro Bot

Bot Discord multi-servidor para a comunidade de GTA RP "Morro do Mineiro".
Python + discord.py, banco SQLite, hospedado em VM Oracle Cloud sob systemd (`farmbot.service`).

## Estrutura

| Pasta | O que tem |
|---|---|
| `main.py` | Entrada do bot: intents, carga dos cogs, sync dos slash commands |
| `cogs/` | Um modulo por sistema do bot (farm, bau, acao, paineis...). Registrados em `core/extensions.py` |
| `core/` | Infra compartilhada: config, logger, permissoes, helpers de data/apelido/cargo |
| `services/` | Acesso a dados e schema do SQLite (`db_service.py`, `db_schema.py`) |
| `config/` | Layout declarativo dos paineis (botoes, permissoes) |
| `assets/` | Imagens usadas em embeds |
| `data/` | Banco `farm.db` e JSONs de configuracao (**nao versionado**) |
| `logs/` | Logs por sistema (**nao versionado**) |
| `tests/` | Testes com pytest |
| `scripts/` | Automacoes de operacao (deploy, token, precos) |
| `docs/` | Documentacao e checklists |

Nem todo arquivo em `cogs/` e um cog: `bau_core.py`, `farm_embeds.py` e `set_views.py`
sao modulos de apoio importados por outros cogs, por isso nao aparecem em `core/extensions.py`.

## Contexto para agentes

Antes de alterar o projeto, leia `AGENTS.md`, `PRODUCT.md` e os documentos
canônicos em `docs/`. Eles registram a arquitetura atual, os contratos do
Discord, os comandos de validação, os riscos operacionais e o procedimento de
rollback.

- `AGENTS.md`: regras compartilhadas para agentes e limites de operação.
- `PRODUCT.md`: propósito, público, fluxos e critérios de preservação.
- `docs/architecture.md`: módulos, inicialização, persistência e integrações.
- `docs/onboarding.md`: preparação local e primeiro diagnóstico.
- `docs/quality.md`: testes automatizados e validação manual.
- `docs/setup.md`: estado atual, evidências, decisões e pendências.
- `docs/operations-security.md`: confirmação, produção, segredos e rollback.

Os documentos de fases em `docs/FASE_*.md` e análises antigas são registros
históricos. Quando houver conflito, o código atual e os documentos canônicos
acima têm precedência; o conflito deve ser registrado antes de qualquer
alteração de comportamento.

## Rodando local

```bash
python -m venv venv
venv/Scripts/Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Requer um `.env` na raiz. O restante da configuracao (canais, cargos, metas) e por servidor,
feita via slash commands e guardada na tabela `guild_config`.

| Variavel | Obrigatoria | Padrao |
|---|---|---|
| `DISCORD_TOKEN` | sim | — |
| `APPLICATION_ID` | sim | — |
| `ARQUIVO_BANCO_FARM` | nao | `farm.db` (dentro de `data/`) |
| `FUSO_HORARIO_FARM` | nao | `America/Sao_Paulo` |
| `CANAL_LOG_ENTRADA_ID` | nao | canal legado fixo no codigo |
| `CANAL_LOG_PD_ID` | nao | canal legado fixo no codigo |

As duas ultimas sao canais globais legados; prefira a configuracao por servidor quando existir.
Todas sao lidas em `core/config.py`.

Os intents privilegiados **Server Members** e **Message Content** precisam estar ligados
no Discord Developer Portal.

## Operacao

```bash
pwsh scripts/deploy.ps1
```

Publica somente o manifesto de runtime rastreado no commit atual. Antes de
abrir SSH, exige arvore limpa, `git diff --check`, testes aprovados e
confirmacao do commit. Cada arquivo substituido recebe backup remoto; o
identificador exibido pode ser usado em:

```bash
pwsh scripts/rollback_deploy.ps1 -BackupId "<identificador>"
```

SSH usa validacao obrigatoria da host key. O host deve existir no `known_hosts`
padrao ou em arquivo indicado por `MORRO_BOT_KNOWN_HOSTS`.

```bash
pwsh scripts/atualizar_token.ps1
```

Usado quando o token do bot e redefinido. Valida o token novo contra a API do Discord antes
de enviar (um token revogado e bem-formado derruba o servico em loop), transfere
somente `DISCORD_TOKEN`, ativa o segredo em `.env.token` de forma atomica e
reinicia. O valor, o tamanho e o fingerprint nao sao exibidos. O `.env`
completo nunca e enviado nem reescrito.

Deploy, rollback, SSH, atualizacao de token, exclusao, alteracao de ACL e
`git push` exigem confirmacao especifica. Consulte
`docs/operations-security.md`.

## Testes

```bash
venv/Scripts/python.exe -m pytest tests/ -q
```

O CI executa o mesmo conjunto com Python 3.12. O comando de teste não conecta
ao Discord nem substitui a validação manual descrita em
`docs/CHECKLIST_INTERACOES.md`.
