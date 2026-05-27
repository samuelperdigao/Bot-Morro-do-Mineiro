"""
cogs/anuncio.py - Sistema de Anúncios para o bot Morro do Mineiro.
"""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from core.logger import get_logger
from services.log_service import send_log
from services.db_service import get_conn, db_get_guild_config, db_set_guild_config

log = get_logger("anuncio", "anuncio.log")


# ── Migração de colunas ────────────────────────────────────────────────────────

def _ensure_anuncio_columns():
    conn = get_conn()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(guild_config)").fetchall()]
    if "canal_anuncio_id" not in cols:
        conn.execute("ALTER TABLE guild_config ADD COLUMN canal_anuncio_id TEXT")
    if "cargos_anuncio" not in cols:
        conn.execute("ALTER TABLE guild_config ADD COLUMN cargos_anuncio TEXT")
    conn.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_ids(raw: str) -> list[int]:
    ids = []
    for part in raw.replace(",", " ").split():
        part = part.strip("<@&>").strip()
        if part.isdigit():
            ids.append(int(part))
    return ids


def db_get_anuncio_canal(guild_id: str) -> int | None:
    cfg = db_get_guild_config(guild_id)
    if not cfg or not cfg["canal_anuncio_id"]:
        return None
    return int(cfg["canal_anuncio_id"])


def db_get_anuncio_cargo_ids(guild_id: str) -> list[int]:
    cfg = db_get_guild_config(guild_id)
    if not cfg or not cfg["cargos_anuncio"]:
        return []
    return [int(x.strip()) for x in cfg["cargos_anuncio"].split(",") if x.strip()]


def pode_anunciar(member: discord.Member, cargo_ids: list[int]) -> bool:
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    return bool({r.id for r in member.roles} & set(cargo_ids))


# ── Modal ─────────────────────────────────────────────────────────────────────

class AnuncioModal(discord.ui.Modal, title="Novo Anúncio"):
    titulo = discord.ui.TextInput(
        label="Título do anúncio",
        placeholder="Ex: Reunião da liderança",
        max_length=256,
    )
    conteudo = discord.ui.TextInput(
        label="Conteúdo",
        style=discord.TextStyle.paragraph,
        placeholder="Escreva o conteúdo do anúncio aqui...",
        max_length=2000,
    )
    mencionar_todos = discord.ui.TextInput(
        label="Mencionar @everyone? (sim/não)",
        placeholder="sim ou não",
        max_length=3,
        required=False,
    )
    adicionar_arquivo = discord.ui.TextInput(
        label="Adicionar arquivo? (sim/não)",
        placeholder="sim ou não — se sim, você enviará o arquivo após confirmar",
        max_length=3,
        required=False,
    )

    def __init__(self, canal_anuncio: discord.TextChannel):
        super().__init__()
        self.canal_anuncio = canal_anuncio

    async def on_submit(self, interaction: discord.Interaction):
        mencionar    = self.mencionar_todos.value.strip().lower()  in ("sim", "s", "yes", "y", "1")
        com_arquivo  = self.adicionar_arquivo.value.strip().lower() in ("sim", "s", "yes", "y", "1")

        embed = discord.Embed(
            title=f"📢 {self.titulo.value.strip()}",
            description=self.conteudo.value.strip(),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"Anunciado por {interaction.user.display_name}")
        content = "@everyone" if mencionar else None

        if not com_arquivo:
            await self.canal_anuncio.send(content=content, embed=embed)
            log.info(
                f"{interaction.user} publicou anúncio '{self.titulo.value.strip()}' "
                f"no canal {self.canal_anuncio.id} (everyone={mencionar})"
            )
            await interaction.response.send_message("✅ Anúncio publicado com sucesso!", ephemeral=True)

            log_embed = discord.Embed(
                title="📢 Anúncio Publicado",
                color=0xFFD700,
                timestamp=discord.utils.utcnow(),
            )
            log_embed.add_field(name="👤 Por", value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=True)
            log_embed.add_field(name="📣 Título", value=self.titulo.value.strip(), inline=True)
            log_embed.add_field(name="📍 Canal", value=self.canal_anuncio.mention, inline=True)
            log_embed.add_field(name="👥 @everyone", value="Sim" if mencionar else "Não", inline=True)
            log_embed.set_footer(text="Morro do Mineiro — Sistema de Anúncio")
            await send_log(interaction.client, interaction.guild, "anuncio", log_embed)
            return

        # ── Fluxo com arquivo: pede ao usuário que envie o arquivo no canal ────
        await interaction.response.send_message(
            "📎 Envie o arquivo como mensagem neste canal em até **60 segundos**.\n"
            "Você pode enviar imagens, vídeos, PDFs ou qualquer outro tipo de arquivo.",
            ephemeral=True,
        )

        def check(msg: discord.Message) -> bool:
            return (
                msg.author.id    == interaction.user.id
                and msg.channel.id == interaction.channel_id
                and len(msg.attachments) > 0
            )

        try:
            msg = await interaction.client.wait_for("message", check=check, timeout=60.0)
        except asyncio.TimeoutError:
            await interaction.followup.send(
                "⏱️ Tempo esgotado. O anúncio foi publicado sem arquivo.", ephemeral=True
            )
            await self.canal_anuncio.send(content=content, embed=embed)
            log.info(
                f"{interaction.user} publicou anúncio '{self.titulo.value.strip()}' "
                f"sem arquivo (timeout) no canal {self.canal_anuncio.id}"
            )
            return

        # Remove a mensagem do canal de painel (era só para upload)
        try:
            await msg.delete()
        except Exception:
            pass

        files = [await att.to_file(use_cached=True) for att in msg.attachments]

        # Se for uma única imagem, exibe dentro do embed
        if len(files) == 1 and msg.attachments[0].content_type and \
                msg.attachments[0].content_type.startswith("image/"):
            embed.set_image(url=f"attachment://{msg.attachments[0].filename}")

        await self.canal_anuncio.send(content=content, embed=embed, files=files)
        log.info(
            f"{interaction.user} publicou anúncio '{self.titulo.value.strip()}' "
            f"com {len(files)} arquivo(s) no canal {self.canal_anuncio.id} (everyone={mencionar})"
        )
        await interaction.followup.send("✅ Anúncio publicado com arquivo!", ephemeral=True)

        log_embed = discord.Embed(
            title="📢 Anúncio Publicado",
            color=0xFFD700,
            timestamp=discord.utils.utcnow(),
        )
        log_embed.add_field(name="👤 Por", value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=True)
        log_embed.add_field(name="📣 Título", value=self.titulo.value.strip(), inline=True)
        log_embed.add_field(name="📍 Canal", value=self.canal_anuncio.mention, inline=True)
        log_embed.add_field(name="👥 @everyone", value="Sim" if mencionar else "Não", inline=True)
        log_embed.add_field(name="📎 Arquivos", value=f"`{len(files)}`", inline=True)
        log_embed.set_footer(text="Morro do Mineiro — Sistema de Anúncio")
        await send_log(interaction.client, interaction.guild, "anuncio", log_embed)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error(f"Erro no AnuncioModal: {error}", exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erro ao publicar anúncio.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Erro ao publicar anúncio.", ephemeral=True)
        except Exception:
            pass


# ── View (painel permanente) ──────────────────────────────────────────────────

class AnuncioPainelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📢 Novo Anúncio", style=discord.ButtonStyle.primary, custom_id="anuncio:novo")
    async def novo_anuncio(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id  = str(interaction.guild_id)
        cargo_ids = db_get_anuncio_cargo_ids(guild_id)

        if not pode_anunciar(interaction.user, cargo_ids):
            await interaction.response.send_message(
                "❌ Você não tem permissão para criar anúncios.", ephemeral=True
            )
            return

        canal_id = db_get_anuncio_canal(guild_id)
        if not canal_id:
            await interaction.response.send_message(
                "❌ Canal de anúncios não configurado. Um admin deve usar `/setup_anuncio`.", ephemeral=True
            )
            return

        canal = interaction.guild.get_channel(canal_id)
        if canal is None:
            try:
                canal = await interaction.guild.fetch_channel(canal_id)
            except Exception:
                await interaction.response.send_message(
                    "❌ Canal de anúncios não encontrado. Reconfigure com `/setup_anuncio`.", ephemeral=True
                )
                return

        await interaction.response.send_modal(AnuncioModal(canal_anuncio=canal))


# ── Cog ───────────────────────────────────────────────────────────────────────

class AnuncioCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setup_anuncio", description="Configura o canal e cargos do sistema de anúncios.")
    @app_commands.describe(
        canal="Canal onde os anúncios serão publicados",
        cargos="IDs ou menções dos cargos autorizados a anunciar (separados por vírgula)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_anuncio(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        cargos: str,
    ):
        cargo_ids = _parse_ids(cargos)
        if not cargo_ids:
            await interaction.response.send_message(
                "❌ Nenhum cargo válido encontrado. Use IDs numéricos ou menções (@cargo).", ephemeral=True
            )
            return

        guild_id = str(interaction.guild_id)
        db_set_guild_config(
            guild_id,
            canal_anuncio_id=str(canal.id),
            cargos_anuncio=",".join(str(i) for i in cargo_ids),
        )

        cargos_txt = " ".join(f"<@&{i}>" for i in cargo_ids)
        embed = discord.Embed(
            title="✅ Sistema de Anúncios Configurado",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="📢 Canal de anúncios",  value=canal.mention, inline=True)
        embed.add_field(name="🎭 Cargos autorizados", value=cargos_txt,    inline=False)
        log.info(f"{interaction.user} configurou anúncios: canal={canal.id}, cargos={cargo_ids}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setup_anuncio.error
    async def setup_anuncio_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)
        else:
            log.error(f"Erro em /setup_anuncio: {error}", exc_info=True)
            await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)

    @app_commands.command(name="painel_anuncio", description="Posta o painel de anúncios no canal atual.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def painel_anuncio(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        if not db_get_anuncio_canal(guild_id):
            await interaction.response.send_message(
                "❌ Configure o sistema primeiro com `/setup_anuncio`.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="📢 Painel de Anúncios",
            description=(
                "Clique no botão abaixo para publicar um anúncio no canal de anúncios.\n\n"
                "Apenas membros com cargos autorizados podem criar anúncios."
            ),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Morro do Mineiro • Sistema de Anúncios")
        await interaction.channel.send(embed=embed, view=AnuncioPainelView())
        await interaction.response.send_message("✅ Painel postado!", ephemeral=True)
        log.info(f"{interaction.user} postou painel de anúncios em #{interaction.channel}")

    @painel_anuncio.error
    async def painel_anuncio_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Sem permissão para usar este comando.", ephemeral=True)
        else:
            log.error(f"Erro em /painel_anuncio: {error}", exc_info=True)
            await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot):
    _ensure_anuncio_columns()
    bot.add_view(AnuncioPainelView())
    await bot.add_cog(AnuncioCog(bot))
    log.info("AnuncioCog carregado com sucesso.")
