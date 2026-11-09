# Deploy do Bot Morro do Mineiro

## Fluxo diário

```
commit -> push na main -> deploy automático
```

1. Faça a mudança numa branch, abra um PR e espere os testes ficarem verdes.
2. Faça o merge na `main` (ou um push direto na `main`).
3. O GitHub Actions roda os testes e, se passarem, publica o bot sozinho.

Mudanças apenas em `docs/` ou em arquivos `.md` não disparam deploy.

## Ver o resultado

GitHub → aba **Actions** → workflow **Deploy** → o run do seu commit.
O passo **Enviar e aplicar no servidor** mostra o backup, o snapshot e as
últimas linhas do log do bot. Run verde = bot no ar com o commit novo.

Pelo terminal:

```powershell
gh run list --repo samuelperdigao/Bot-Morro-do-Mineiro --workflow deploy.yml
gh run view <id> --repo samuelperdigao/Bot-Morro-do-Mineiro --log-failed
```

## Disparar manualmente

GitHub → **Actions** → **Deploy** → **Run workflow** (branch `main`), ou:

```powershell
gh workflow run deploy.yml --repo samuelperdigao/Bot-Morro-do-Mineiro --ref main
```

## O que acontece no servidor (`scripts/remote_deploy.sh`)

1. Backup de `data/*.db` e `bau.db` com a API de backup do SQLite em
   `backups/predeploy-<banco>-<data>.db.gz` (guarda os 10 mais recentes de cada).
2. Snapshot do código atual em `~/farmbot-releases/` (guarda os 5 mais recentes).
3. Extrai a release em pasta temporária e roda `venv/bin/pip install`.
   Se falhar, para sem alterar o código do bot.
4. Copia só o código de runtime (`assets/ cogs/ config/ core/ features/
   infrastructure/ services/ ui/ main.py requirements.txt`), igual ao
   `scripts/deploy.ps1`. `.env`, `data/`, bancos, JSON de estado e chaves
   nunca são tocados.
5. Reinicia o `farmbot` e confere o status a cada segundo por 40s. Se cair,
   restaura os arquivos anteriores, reinicia e o run fica vermelho.

As dependências instaladas no passo 3 não voltam no rollback.

## Configuração (uma vez só)

Secrets em **Settings → Secrets and variables → Actions**:

| Secret | Conteúdo |
|---|---|
| `ORACLE_SSH_KEY` | conteúdo do arquivo `oracle.key` |
| `ORACLE_KNOWN_HOSTS` | saída de `ssh-keyscan 163.176.143.142` |

Sem eles, o push na `main` só roda os testes e termina com aviso; o disparo
manual falha com mensagem explicando o que falta.

## Plano B: deploy manual pelo PC

```powershell
pwsh scripts/deploy.ps1
```

Ver `README.md` e `docs/operations-security.md`.

## Restaurar um backup dos bancos

```bash
cd /home/ubuntu/farmbot
sudo systemctl stop farmbot
rm -f data/farm.db-wal data/farm.db-shm
gunzip -c backups/predeploy-farm-AAAAMMDD-HHMMSS.db.gz > data/farm.db
sudo systemctl start farmbot
```

Para o baú, use `bau.db` (na raiz) e `backups/predeploy-bau-*.db.gz`.

Além dos backups de deploy, o bot gera todo dia às 04:00 (Brasília)
`backups/farm-*.db.gz` e `backups/bau-*.db.gz`, mantendo os 14 mais recentes
de cada. Administradores podem gerar um na hora com `/backup_agora`. Esses
arquivos se restauram do mesmo jeito.

## Variáveis opcionais no `.env` do servidor

| Variável | Para que serve |
|---|---|
| `CANAL_ERROS_ID` | Canal privado que recebe avisos de erro do bot (1 por erro a cada 10 min) |
| `CANAL_BACKUP_ID` | Canal privado que recebe o backup diário dos bancos |

Sem elas, erros e backups ficam só no servidor (`logs/` e `backups/`).
Depois de editar o `.env`, reinicie com `sudo systemctl restart farmbot`.
