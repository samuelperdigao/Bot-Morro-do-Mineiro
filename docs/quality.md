# Qualidade e validação

## Gate automatizado atual

O comando canônico é:

```powershell
.\venv\Scripts\python.exe -m pytest tests/ -q
```

O CI em `.github/workflows/tests.yml` usa Ubuntu, Python 3.12, instala
`requirements.txt` e `pytest`, e executa `python -m pytest tests/ -q` em pull
requests.

Baseline local registrado em 18/10/2026, antes da adoção documental:

```text
256 passed, 11 warnings, 21 subtests passed in 6.70s
```

Após o endurecimento operacional, a suíte local registrou:

```text
270 passed, 11 warnings, 21 subtests passed in 7.23s
```

O teste foi executado na venv do projeto, sem conexão ao Discord, sem produção
e sem deploy. O plugin de cache do pytest foi desabilitado nessa auditoria para
evitar gerar cache adicional.

## Avisos conhecidos

- `discord.player` ainda emite depreciação relacionada a `audioop`.
- Algumas asserções e componentes usam propriedades de UI marcadas como
  deprecated, com recomendação de `discord.ui.Label`.

Esses avisos não foram corrigidos nesta etapa. Não devem ser silenciados com
filtros amplos nem usados como justificativa para uma migração visual ampla.

## Cobertura existente

Os testes cobrem, entre outros:

- serviços de Set, Ação, Farm e Baú;
- schema, migrações idempotentes e preservação de dados legados;
- views persistentes, containers e `custom_id`;
- permissões, cargos, apelidos, datas, ranking e recolhimento;
- fluxos de tickets, advertências, coletes e layouts de painéis.
- controles estáticos dos scripts operacionais: confirmação, host key,
  manifesto rastreado, não envio do `.env` e rollback.

Não existe atualmente uma configuração versionada de Ruff, Pyright, Mypy,
coverage, formatter ou gate de type-check. A adoção dessas ferramentas é uma
decisão futura, separada desta etapa.

## Validação manual

Use `docs/CHECKLIST_INTERACOES.md` para testar uma guild autorizada. A
validação manual deve observar resposta em até três segundos, permissões,
views após reinício, erros de interação e logs sem traceback inesperado.

Testes locais não provam:

- sincronização global de comandos no Discord;
- existência ou validade dos IDs em uma guild real;
- permissões reais de cargos, canais e intents;
- comportamento do serviço `systemd` na Oracle Cloud;
- segurança ou sucesso de deploy.

## Critérios para mudanças

Uma mudança deve ter teste de regressão ou caracterização quando houver risco
de alterar comportamento. Mudanças em schema devem testar idempotência e
preservação de dados em banco temporário. Mudanças em views devem preservar
`timeout`, callbacks e `custom_id` existentes.

Mudanças em scripts PowerShell devem passar pelos testes de segurança
operacional e pelo parser do PowerShell sem executar o conteúdo do script.
Essa validação não substitui uma execução controlada em ambiente de staging.

O comando histórico `compileall` aparece nos relatórios de fases, mas gera
arquivos `.pyc`; não é tratado como verificação estritamente somente leitura.
