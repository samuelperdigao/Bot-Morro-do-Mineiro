# Instruções compartilhadas do projeto

## Escopo

Este repositório contém o bot Discord multi-servidor do Morro do Mineiro.
Antes de agir, leia este arquivo, `PRODUCT.md` e os documentos canônicos em
`docs/`. Leia também as instruções específicas do diretório quando existirem.

## Fontes de verdade

- Código atual: comandos, extensões, views, `custom_id`, permissões e contratos.
- `core/extensions.py`: extensões carregadas no startup.
- `README.md`: entrada rápida, execução local e operação.
- `PRODUCT.md`: propósito, escopo e critérios de preservação.
- `docs/architecture.md`: estrutura e limites técnicos.
- `docs/onboarding.md`: preparação e diagnóstico local.
- `docs/quality.md`: testes e evidências de qualidade.
- `docs/setup.md`: decisões, estado, riscos e manutenção do contexto.
- `docs/operations-security.md`: autorização, produção, segredos e rollback.
- `docs/CHECKLIST_INTERACOES.md`: validação manual no Discord.
- `docs/FASE_*.md` e `docs/CHANGELOG.md`: histórico; não são automaticamente
  a descrição do estado atual.

Quando uma fonte histórica divergir do código, registre a divergência e use o
código atual para descrever o comportamento. Não transforme uma hipótese em
funcionalidade documentada.

## Stack e comandos canônicos

- Python 3.12 é a versão testada localmente e no CI.
- Dependências de runtime estão em `requirements.txt`.
- O banco principal é SQLite; a configuração por servidor é persistida no
  banco e os dados operacionais não são versionados.
- Ambiente local:

  ```powershell
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  python -m pip install -r requirements.txt
  ```

- Testes:

  ```powershell
  .\venv\Scripts\python.exe -m pytest tests/ -q
  ```

- Execução do bot: `python main.py`. Requer `.env`, token válido, application
  ID e intents privilegiados configurados no Discord Developer Portal.

O comando `pwsh scripts/deploy.ps1` é operação de produção, não validação
local. `scripts/atualizar_token.ps1` envia somente a credencial selecionada ao
servidor; ele nunca deve enviar o `.env` completo. Nenhum dos dois deve ser
executado durante diagnóstico, teste ou revisão documental.

## Regras de mudança

- Preserve comandos slash, permissões, mensagens, embeds, views persistentes e
  `custom_id` existentes, salvo decisão explícita.
- Não altere banco, migrações, JSONs operacionais ou dados de produção durante
  uma tarefa documental ou de diagnóstico.
- Stack, package manager, dependências, CI e compatibilidades legadas devem ser
  preservados. Migração de framework, ORM, banco ou versão major exige decisão
  separada.
- Não execute SSH, deploy, publicação, comandos remotos ou scripts com efeitos
  externos sem autorização específica.
- Não leia, imprima ou versione segredos de `.env` e chaves SSH.
- Faça a menor mudança verificável. Um arquivo de configuração compartilhada
  ou lockfile deve ter um único responsável por vez.
- Atualize o documento responsável quando comportamento, comando, schema,
  limite ou procedimento mudar.

## Autorização de operações externas

- SSH, SCP, deploy, rollback remoto, alteração de token, exclusão, mudança de
  ACL e `git push` exigem confirmação específica do usuário na conversa atual.
- A confirmação deve identificar ação, alvo e escopo. Não reutilize uma
  confirmação para outra ação ou turno.
- Acesso SSH somente para leitura também exige confirmação.
- O parâmetro `-ConfirmedByUser` só pode ser usado depois dessa confirmação.
- Preparação local, testes e análise estática não autorizam produção.
- Não mostre nem inclua em relatórios tokens, senhas, chaves privadas ou o
  conteúdo do `.env`.
- Não copie nem envie o `.env` completo. Atualizações devem tratar uma variável
  por vez e manter o valor oculto.
- Limpeza de temporários criados pela própria operação faz parte da operação
  confirmada; qualquer outra exclusão exige confirmação própria.

## Evidência e recuperação

Antes de implementar, registre estado do Git, arquivos afetados, critérios de
aceitação e comandos de verificação. Diferencie fato observado, hipótese,
decisão e evidência.

Mudanças devem ser atômicas e reversíveis. Antes de qualquer mudança em
configuração, preserve o conteúdo relevante sem incluir segredos. Para
mudanças já commitadas, prefira `git revert` do commit específico. Não use
reset destrutivo nem restaure o banco automaticamente como forma de rollback.
