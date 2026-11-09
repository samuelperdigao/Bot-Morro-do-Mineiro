# Deploy do Bot Morro do Mineiro

## Opção A: pelo GitHub (recomendado, funciona de qualquer lugar)

**Configuração (uma vez só):**
1. No GitHub, abra **Settings → Secrets and variables → Actions → New repository secret**.
2. Crie o secret `ORACLE_SSH_KEY` com o conteúdo inteiro do arquivo `scripts/oracle.key` do seu PC.
3. Opcional, mas recomendado: crie o secret `ORACLE_KNOWN_HOSTS` com a saída de `ssh-keyscan 163.176.143.142`. Isso fixa a identidade do servidor.

**Uso:**
- Todo merge ou push na `main` roda os testes e, se eles passarem, publica o bot sozinho.
- Para publicar manualmente: **Actions → Deploy → Run workflow**.
- Enquanto o secret não existir, o push na `main` só roda os testes e termina com um aviso, sem publicar.

## Opção B: pelo PC (Windows)

```powershell
.\deploy.ps1
```

O script precisa de `git`, `ssh` e `scp` (OpenSSH do Windows) e de `scripts/oracle.key`. Ele envia **só o último commit**: alterações não commitadas não vão para o servidor.

## O que acontece no servidor (`scripts/remote_deploy.sh`)

1. Faz backup do `farm.db` e do `bau.db` em `backups/predeploy-*.db.gz` (guarda os 10 mais recentes).
2. Tira um snapshot do código atual em `~/farmbot-releases/` (guarda os 5 mais recentes).
3. Extrai a nova versão numa pasta temporária e instala as dependências. Se essa etapa falhar, nada é alterado.
4. Copia a nova versão para a pasta do bot e reinicia o serviço `farmbot`.
5. Acompanha o serviço por 40s. Se o bot não ficar de pé, **restaura a versão anterior** e o deploy falha.

O deploy **nunca** leva `.env`, chaves, bancos ou JSON de estado. Esses arquivos ficam como estão no servidor.

## Variáveis opcionais no `.env` do servidor

| Variável | Para que serve |
|---|---|
| `CANAL_ERROS_ID` | Canal privado que recebe avisos de erro do bot |
| `CANAL_BACKUP_ID` | Canal privado que recebe o backup diário (04:00) do `farm.db` e do `bau.db` |

Sem essas variáveis, erros e backups ficam só no servidor (`logs/` e `backups/`).

## Primeiro deploy desta versão: o que conferir

- O discord.py sobe de 2.3.2 para 2.7.1. O deploy instala sozinho.
- No primeiro start, as tabelas novas (`set_solicitacoes`, `acoes`, `acao_inscritos`) e a coluna `ferro` do recolhimento são criadas automaticamente.
- Os comandos do Ponto somem. Apague manualmente a mensagem do painel de ponto que ficou no canal.
- Painéis de Ação abertos antes do deploy deixam de aceitar mudanças e avisam para iniciar uma ação nova.
- Pedidos de set pendentes continuam funcionando.
- Confira se o `.env` do servidor está correto: o deploy antigo enviava o `.env` local por cima do de produção.

## Restaurar um backup manualmente

```bash
cd /home/ubuntu/farmbot
sudo systemctl stop farmbot
gunzip -c backups/predeploy-farm-AAAAMMDD-HHMMSS.db.gz > data/farm.db
sudo systemctl start farmbot
```
