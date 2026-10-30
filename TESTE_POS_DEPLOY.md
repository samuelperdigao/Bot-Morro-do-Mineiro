# Teste depois do deploy

Use um membro de teste. No fim, corrija os lançamentos dele para 0.
**Não mude a meta da semana para testar:** quem tem ticket aberto e deixa de cobrir a nova meta perde a aprovação. Ela volta sozinha se você restaurar o valor, mas o membro recebe de novo os avisos de conclusão.
Se algo falhar, anote o passo e a mensagem. Para voltar a versão: `.\rollback.ps1`.

## 1. Ranking
1. No ticket do membro de teste, use **📦 Lançar Farm** e lance o dobro da meta em um item só e envie o print. Resultado: o lançamento é aceito.
2. Rode `/ranking`. Resultado: o percentual conta só esse item (meta de 4 itens = 25%) e ele aparece como Parcial.
3. Se dois membros tiverem a mesma classificação e 100%, resultado: fica acima quem concluiu primeiro.

## 2. Meta que volta para em andamento
1. Lance até completar a meta. Resultado: "🏆 Meta batida: aprovação registrada automaticamente."
2. Como liderança, use **🔍 Revisar lançamentos** > escolha o lançamento > **Corrigir valores** e baixe o valor. Resultado: "Lançamento corrigido."
3. Rode `/resultado` e abra a lista. Resultado: o membro aparece como "Em Andamento | Pendente".
4. Lance o que falta. Resultado: a aprovação automática volta.

## 3. Aprovação de Set
1. Com o membro de teste, clique em **📝 Fazer Set** e preencha. Resultado: o pedido chega no canal de aprovação com **✅ Aprovar** e **❌ Reprovar**.
2. Clique em **✅ Aprovar**. Resultado: os botões somem e o canal de log mostra "✅ Set Aprovado".
3. Peça um Set de uma conta que depois saia do servidor e clique em **✅ Aprovar**. Resultado: "Membro não encontrado" e os botões continuam na mensagem.
4. Se houver um pedido antigo com botões no canal, clique em **❌ Reprovar**. Resultado: o log mostra "❌ Set Reprovado". Se os dados não puderem ser lidos, o bot pede que o membro refaça o Set.

## 4. Painel de ação
1. Rode `/acao`, escolha o tipo e preencha. Resultado: o seletor de ação aparece no canal.
2. Com um membro sem liderança, use o seletor. Resultado: "❌ Apenas liderança pode iniciar ação." e nada é criado.
3. Como liderança, escolha **Loja de Tatuagens** (limite de 2). Três pessoas clicam em **✅ Entrar na ação**. Resultado: a terceira recebe "❌ Vagas esgotadas (máximo: 2)."
4. Clique em **🔒 Finalizar ação** para encerrar. Se houver um painel antigo sem registro, um clique nele responde "❌ Painel indisponível." e os botões somem.

## 5. Apelido
1. Faça um Set com nome bem longo (mais de 30 letras) e ID `123456789`, depois aprove. Resultado: o apelido fica `[MBR] Nome cortado | 123456789`, com o ID inteiro.
2. Aprove um Set de quem tem cargo acima do bot. Resultado: o Set é aprovado e o canal de log mostra "⚠️ Sem permissão para alterar apelido".

## 6. Ausência
1. Rode `/ausencias`. Resultado: quem estava ausente antes do deploy continua na lista.
2. No painel (`/painel_ausencia`), use **📋 Registrar Ausência** com 1 dia. Resultado: o registro sai no canal configurado em `/setup_ausencia` e o membro aparece em `/ausencias`.
3. Registre outra ausência com o mesmo membro, agora com 2 dias. Resultado: `/ausencias` continua com uma linha só para ele, com a data nova.
4. Espere os 2 dias (até 1 hora depois do prazo). Resultado: chega uma DM só, "⏰ Sua ausência venceu hoje".
