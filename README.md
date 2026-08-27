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

## Rodando local

```bash
python -m venv venv
venv/Scripts/activate
pip install -r requirements.txt
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

Envia a arvore de trabalho local para a VM e reinicia o servico. Atencao: envia o que esta
no disco, nao o HEAD do git — mudancas nao commitadas vao para producao.

```bash
pwsh scripts/atualizar_token.ps1
```

Usado quando o token do bot e redefinido. Valida o token novo contra a API do Discord antes
de enviar (um token revogado e bem-formado e derruba o servico em loop), confere o fingerprint
SHA256 no servidor e so entao reinicia. `deploy.ps1` nao envia o `.env` de proposito.

## Testes

```bash
python -m pytest tests/ -q
```
