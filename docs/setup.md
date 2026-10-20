# Estado e manutenção do contexto

## Registro desta etapa

- Data: 18/10/2026.
- Escopo: Etapa 1 — documentação e instruções.
- Fonte do toolkit: README e Prompt 12 publicados em `main`:
  `https://github.com/soumatheusgomes/vibe-coding-toolkit`.
- Revisão exata do toolkit: não fixada nesta etapa; a fonte remota foi usada
  como referência atual.
- Branch: `refactor/organizar-estabilizar-bot`.
- Estado anterior: working tree limpo e branch um commit à frente de `origin`.
- Cliente de instruções: `AGENTS.md` é a fonte compartilhada. `CLAUDE.md` não
  foi criado porque esta etapa é executada no Codex e não há instrução
  específica de Claude necessária.

## Arquivos desta adoção

| Arquivo | Papel | Estado |
|---|---|---|
| `AGENTS.md` | Instruções compartilhadas e limites | criado |
| `PRODUCT.md` | Produto, escopo e critérios de preservação | criado |
| `docs/architecture.md` | Arquitetura e limites atuais | criado |
| `docs/onboarding.md` | Preparação e diagnóstico local | criado |
| `docs/quality.md` | Testes, evidências e limitações | criado |
| `docs/setup.md` | Registro, decisões e manutenção | criado |
| `README.md` | Índice de contexto e comandos atualizados | atualizado |
| `docs/INVENTARIO_BOT.md` | Inventário alinhado ao código ativo | atualizado |
| `docs/PAINEIS.md` | Persistência de `ApprovalView` corrigida | atualizado |

Na adoção documental inicial acima não foram alterados banco, migrações, dados,
`requirements.txt` ou configurações remotas. O endurecimento operacional desta
etapa alterou `core/config.py`, `.gitignore`, os scripts de deploy, token e
preços, criou `scripts/rollback_deploy.ps1` e
`tests/test_operational_security.py`, e atualizou a documentação e as
configurações locais de agente. Nenhum comando Discord, view, banco ou dado de
produção foi alterado.

## Evidências

- `core/extensions.py` foi usado como fonte da lista de extensões ativas.
- `main.py` e `cogs/set_views.py` comprovam o registro e a recuperação de
  views persistentes.
- O código e `docs/FASE_7_DASHBOARD_LEGADO.md` comprovam que
  `cogs.dashboard` não está ativo na tupla atual.
- Testes locais da adoção documental inicial: `256 passed, 11 warnings, 21 subtests passed`.
- Nenhuma validação contra Discord real, produção, SSH ou systemd foi feita.

## Decisões e pendências

- A stack Python/`discord.py`/SQLite foi preservada.
- Não foram instaladas ferramentas adicionais de lint, type-check, grafo ou
  memória externa.
- `.claude/settings.json` foi reduzido a verificações locais e será versionado;
  `settings.local.json` não concede comandos automaticamente e continua local.
- `cogs/dashboard.py` permanece como legado não carregado. Mensagens antigas no
  Discord ainda precisam de confirmação manual antes de qualquer reativação.
- `docs/ANALISE_CODIGO.md`, `docs/BASELINE_FASE_1.md`, `docs/FASE_*.md` e
  `docs/CHANGELOG.md` continuam registros históricos; não devem ser lidos como
  inventário automaticamente atualizado.
- Não há gate de lint, type-check ou cobertura versionado.

## Endurecimento operacional

Em 18/10/2026 foram preparados controles locais para deploy, rollback e troca
de token, sem acessar produção:

- operações externas exigem confirmação específica;
- SSH valida a host key e não aceita fallback inseguro;
- deploy recusa árvore suja, executa testes e envia somente manifesto rastreado;
- arquivos substituídos recebem backup remoto para rollback;
- atualização de token transfere somente `DISCORD_TOKEN`, nunca o `.env`;
- testes estáticos caracterizam esses contratos.

Evidência local: `270 passed, 11 warnings, 21 subtests passed` e parsing sem
erros dos quatro scripts PowerShell. A validação não executou o conteúdo dos
scripts operacionais.

Não foram executados SSH, deploy, rollback, troca de token, alteração de ACL,
commit ou push. A restrição das ACLs locais continua pendente de confirmação
específica das identidades que devem manter acesso.

## Verificação e manutenção

Após mudanças de comportamento, execute os testes relevantes, revise o diff e
atualize o documento responsável. Após mudanças de configuração, registre a
versão, o escopo, o comando de validação e a forma de recuperação.

Antes de uma nova adoção do toolkit, releia as fontes remotas e compare este
registro com o estado real do checkout. Não presuma que uma instalação, skill,
MCP, hook ou integração carregada em outra sessão continua disponível.

## Rollback documental

Antes de um commit, preserve o diff e reverta somente os arquivos documentais
desta etapa. Depois de um commit, use `git revert` do commit específico. Não
use `git reset --hard`, não restaure o banco e não reverta dependências ou
código como efeito colateral de um rollback documental.
