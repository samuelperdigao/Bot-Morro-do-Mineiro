# Produto: Morro do Mineiro Bot

## Propósito observado

O Morro do Mineiro Bot é um bot Discord multi-servidor para apoiar a operação
da comunidade de GTA RP Morro do Mineiro. Ele reúne comandos slash, painéis,
views persistentes, permissões por cargo e persistência local em SQLite.

Este documento descreve o produto a partir do código e da documentação
existentes. Não cria requisitos para funcionalidades que ainda não foram
confirmadas.

## Usuários e responsabilidades observadas

- Membros da comunidade usam os fluxos de Set, Farm, Ação, Baú, Colete,
  ausência, encomendas, anúncios, rádio e consultas relacionadas.
- Liderança e gerência executam aprovações, configurações, recolhimentos,
  relatórios, advertências e operações administrativas conforme as permissões
  configuradas.
- Administradores configuram canais, cargos e painéis por servidor.

Os nomes e permissões efetivos continuam sendo definidos pelo código e pela
configuração de cada guild. A existência de um comando não prova que ele está
configurado ou ativo em um servidor real.

## Fluxos críticos a preservar

- Inicialização do bot, carga das extensões e sincronização dos comandos.
- Set e aprovação de membros, incluindo recuperação de solicitações pendentes.
- Farm, metas, tickets, lançamentos, revisão, aprovação e relatórios.
- Ações e participantes, com proteção contra duplicidade.
- Painéis persistentes e variantes Components V2 que reutilizam callbacks
  existentes.
- Baú, fabricação de coletes, recolhimento, permissões, logs e configurações
  por guild.
- Migrações SQLite idempotentes e preservação de dados legados.

## Restrições de produto

- Discord é a interface operacional; não há aplicação web independente neste
  repositório.
- O banco principal é SQLite local. O banco, JSONs operacionais e logs não são
  contratos versionados do Git.
- Existem IDs fixos e fallbacks legados; eles só devem ser removidos após
  confirmação de uso no servidor e estratégia de compatibilidade.
- Views, comandos e permissões podem estar ligados a mensagens já publicadas;
  reordenar ou renomear componentes pode quebrar usuários existentes.
- Deploy e atualização de token são operações separadas e não fazem parte da
  manutenção normal do código.

## Critérios de aceitação para mudanças

Uma mudança de comportamento só deve ser considerada pronta quando:

1. O fluxo afetado possui critério observável e teste automatizado quando
   possível.
2. Comandos, permissões, views, `custom_id` e contratos de dados não afetados
   continuam compatíveis.
3. Migrações, se aprovadas separadamente, são idempotentes e preservam dados.
4. Os testes relevantes passam e as limitações de validação são registradas.
5. A documentação responsável foi atualizada.

## Fora do escopo desta etapa

Não fazem parte da adoção documental: novas funcionalidades, migração de
framework ou banco, troca de ORM, instalação de ferramentas de qualidade,
alteração de scripts operacionais, deploy, acesso remoto ou validação em
produção.
