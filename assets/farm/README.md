# Arte da meta aprovada

O bot anexa a primeira imagem encontrada nesta ordem ao parabenizar o membro
na pasta privada dele (`cogs/farm.py` → `META_APROVADA_IMAGE_PATHS`):

1. `assets/farm/meta-aprovada.png`
2. `assets/farm/meta-aprovada.jpg`
3. `assets/farm_advertencias/logo.jpg` (reserva)

Para trocar a arte, basta salvar o novo arquivo com um desses nomes aqui.

## Logo do ticket de farm

`mdm-logo-original.png` preserva a arte original enviada pelo usuário. O painel
do ticket anexa esse PNG e o exibe em uma galeria de imagem de largura total no
rodapé. A foto de perfil Discord do membro aparece no cabeçalho como miniatura;
a logo não é recortada, esticada nem substituída por uma faixa animada.

O painel procura o emoji com ID `1542674742916419644` e, caso ele seja estático
ou não esteja disponível, escolhe um emoji marcado como animado na guild. A
imagem desse ID identifica a Central mesmo sendo estática; a animação usa um
emoji realmente animado junto ao status. Os blocos têm separadores amplos e as
fileiras de botões ficam no final. Os blocos informativos usam `>>>` para manter
uma barra de citação contínua à esquerda de cada TextDisplay. Os tópicos usam
numeração discreta, e os sete botões ficam em duas fileiras equilibradas (4/3)
sob um cabeçalho compacto. O GIF e o banner `ticket-banner-mineiro` não são
usados pelo painel.
