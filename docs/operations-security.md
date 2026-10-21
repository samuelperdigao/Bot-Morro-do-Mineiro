# Segurança das operações

## Princípio de autorização

Deploy, SSH, SCP, atualização de credencial, alteração de ACL, exclusão e
`git push` continuam disponíveis, mas nunca são autorização implícita de uma
tarefa de desenvolvimento. Cada ação exige confirmação específica na conversa
atual, com alvo e escopo identificados. Uma confirmação não vale para ações
posteriores.

Preparações locais e sem efeito externo, como `git status`, `git diff --check`,
testes e análise estática, não autorizam acesso a produção.

| Ação | Confirmação obrigatória |
|---|---|
| SSH, inclusive leitura | alvo e finalidade do acesso |
| Deploy | commit, branch e ambiente |
| Rollback remoto | identificador do backup e ambiente |
| Atualização de token | variável e ambiente, sem revelar o valor |
| Atualização de preços | canal e autorização para substituir mensagens |
| `git push` | remoto, branch e commits/refspec |
| Exclusão | alvo exato e possibilidade de recuperação |
| Alteração de ACL | arquivos/diretórios e identidades afetadas |

O parâmetro `-ConfirmedByUser` dos scripts operacionais é reservado a agentes
que já receberam essa confirmação específica na conversa atual. Operadores
humanos devem preferir a confirmação interativa exibida pelo script.

## Fluxo guiado de commit e deploy

Para publicar mudanças locais com uma sequência guiada, use:

```powershell
pwsh scripts/publicar.ps1
```

O script:

1. mostra os arquivos alterados e pede confirmação antes de incluí-los;
2. bloqueia arquivos `.env`, chaves, bancos e diretórios `data/` e `logs/`;
3. pede a mensagem e confirmação do commit local;
4. executa a suíte de testes antes do commit;
5. mostra o upstream e os commits exatos antes de confirmar o `git push`;
6. mostra branch, hash completo e ambiente antes de confirmar produção;
7. chama `deploy.ps1`, que repete os testes, valida o manifesto, faz backup e
   só então acessa o servidor.

O fluxo para se a branch estiver atrás do upstream, se houver arquivos fora do
commit ou se qualquer teste, push ou deploy falhar. Se não houver mudanças
locais, ele pode publicar o commit atual após as confirmações de push e deploy.
Atualização de preços e troca de token permanecem operações separadas.

## Segredos

- Nunca imprimir ou incluir em relatórios tokens, senhas, chaves privadas ou o
  conteúdo do `.env`.
- Nunca enviar ou copiar o `.env` completo.
- A atualização de token transfere somente `DISCORD_TOKEN` por arquivo
  temporário com acesso restrito, ativa o segredo em `.env.token` e remove os
  temporários ao concluir. O `.env` original não é reescrito.
- O deploy não inclui `.env`, chaves, bancos, logs ou arquivos não rastreados.
- Falhas devem ser descritas sem reproduzir cabeçalhos HTTP, argumentos ou
  conteúdo que possa conter credenciais.

## Host SSH

Os scripts usam `StrictHostKeyChecking=yes`. A chave pública do servidor deve
estar no `known_hosts` padrão do usuário ou em um arquivo indicado pela variável
`MORRO_BOT_KNOWN_HOSTS`.

O primeiro cadastro ou uma troca de host key deve ser conferido por canal
independente, como o console do provedor. Não aceite uma chave nova apenas
porque a conexão apresentou um fingerprint diferente.

## Deploy

O comando permanece:

```powershell
pwsh scripts/deploy.ps1
```

Antes do primeiro SSH, o script exige:

1. repositório e branch identificados;
2. árvore sem alterações ou arquivos não rastreados;
3. `git diff --check` sem erros;
4. suíte canônica de testes aprovada;
5. manifesto composto somente por arquivos rastreados de runtime;
6. confirmação com o commit que será publicado.

Cada arquivo remoto substituído é preservado em
`.deploy-backups/<identificador>/files`. Arquivos criados pela release ficam
registrados no manifesto do backup. Falha de cópia, instalação, restart ou
saúde solicita rollback automático.

Antes da ativação, todos os arquivos são enviados a uma área de staging e o
SHA-256 remoto é comparado ao arquivo local validado. A ativação só começa
depois que o manifesto inteiro estiver íntegro. Uma troca integral por symlink
depende de validação prévia da unidade `systemd` em produção.

O backup não é removido automaticamente. A retenção e a exclusão posterior
exigem uma operação separada e confirmada.

## Rollback

Use apenas após confirmar o identificador informado pelo deploy:

```powershell
pwsh scripts/rollback_deploy.ps1 -BackupId "<identificador>"
```

O rollback restaura os arquivos anteriores, remove somente os arquivos que a
release registrada criou, reinicia o serviço e verifica o estado `active`. Ele
não altera banco, `.env`, logs ou arquivos fora do manifesto.

Para mudanças já commitadas no repositório, prefira `git revert` do commit
específico. Não use `git reset --hard` como recuperação operacional.

## Atualização de token

O comando permanece:

```powershell
pwsh scripts/atualizar_token.ps1
```

O script confirma a operação antes do acesso externo, valida a credencial no
Discord, transfere somente o valor selecionado, troca `.env.token` de forma
atômica e restaura a credencial anterior se o serviço não iniciar. Sem esse
arquivo opcional, o bot continua usando `DISCORD_TOKEN` do `.env` normal.
Nenhum valor, tamanho ou fingerprint é exibido.

## ACLs locais

A política desejada é:

- `.env` e chaves: usuário responsável, Administradores e SYSTEM;
- configurações do agente e scripts: escrita apenas por contas nomeadas;
- bancos e logs: conta do serviço, usuário responsável e Administradores;
- nenhum acesso genérico de modificação para `Authenticated Users`.

A aplicação dessas ACLs é uma ação separada. Antes dela, registre os descritores
atuais para rollback e confirme as identidades que precisam continuar com
acesso.
