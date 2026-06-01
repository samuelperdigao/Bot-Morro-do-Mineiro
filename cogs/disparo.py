"""Painel administrativo para disparo de mensagens em canais privados."""

from __future__ import annotations

import json
import re
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from core.logger import get_logger

log = get_logger("disparo", "disparo.log")

BROADCAST_CATEGORY_ID = 1474869322387292362
BROADCAST_CHANNEL_PATTERN = re.compile(r"^(?:┃📁-)?┃?\d+-.+-\d+$")
BROADCAST_HISTORY_FILE = Path(__file__).resolve().parent.parent / "data" / "broadcast_messages.json"
MAX_STORED_BATCHES = 10

BLOCKED_CHANNEL_NAMES = {
    "tutorial-de-farm",
    "lançar-farm",
    "lancar-farm",
    "painel-de-operações",
    "painel-de-operacoes",
    "avisos",
    "fichas",
    "▬▬▬▬▬▬▬▬▬▬",
}


def load_broadcast_history() -> dict:
    """Carrega o histórico dos disparos usados pelo botão de exclusão."""
    if not BROADCAST_HISTORY_FILE.exists():
        return {"guilds": {}}

    try:
        with BROADCAST_HISTORY_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        log.error("Falha ao carregar histórico de disparos: %s", exc, exc_info=True)
        return {"guilds": {}}

    if not isinstance(data, dict):
        return {"guilds": {}}

    data.setdefault("guilds", {})
    return data


def save_broadcast_history(data: dict) -> None:
    """Salva o histórico de disparos de forma simples e persistente."""
    BROADCAST_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with BROADCAST_HISTORY_FILE.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def normalize_channel_name(name: str) -> str:
    """Normaliza nomes de canais para comparações conservadoras."""
    return name.lower().strip()


def is_valid_member_channel(channel: discord.abc.GuildChannel) -> bool:
    """Retorna True apenas para pastas privadas individuais da categoria fixa."""
    if not isinstance(channel, discord.TextChannel):
        return False

    if channel.category_id != BROADCAST_CATEGORY_ID:
        return False

    normalized_name = normalize_channel_name(channel.name)

    if normalized_name in BLOCKED_CHANNEL_NAMES:
        return False

    if "livre" in normalized_name:
        return False

    return bool(BROADCAST_CHANNEL_PATTERN.fullmatch(normalized_name))


def register_broadcast_batch(
    guild_id: int,
    author_id: int,
    messages: list[dict[str, int]],
) -> str:
    """Registra o último disparo para permitir exclusão posterior segura."""
    history = load_broadcast_history()
    guild_key = str(guild_id)
    guild_data = history["guilds"].setdefault(guild_key, {"batches": []})
    batches = guild_data.setdefault("batches", [])

    batch_id = f"{guild_id}-{discord.utils.utcnow().strftime('%Y%m%d%H%M%S')}"
    batches.append(
        {
            "id": batch_id,
            "category_id": BROADCAST_CATEGORY_ID,
            "author_id": author_id,
            "created_at": discord.utils.utcnow().isoformat(),
            "messages": messages,
        }
    )
    guild_data["last_batch_id"] = batch_id
    guild_data["batches"] = batches[-MAX_STORED_BATCHES:]
    save_broadcast_history(history)
    return batch_id


def get_latest_active_broadcast_batch(guild_id: int) -> dict | None:
    history = load_broadcast_history()
    guild_data = history.get("guilds", {}).get(str(guild_id), {})
    batches = guild_data.get("batches", [])

    for batch in reversed(batches):
        if batch.get("category_id") == BROADCAST_CATEGORY_ID and not batch.get("deleted_at"):
            return batch

    return None


def mark_broadcast_batch_deleted(
    guild_id: int,
    batch_id: str,
    deleted_by: int,
    deleted_count: int,
    failed_count: int,
) -> None:
    history = load_broadcast_history()
    batches = history.get("guilds", {}).get(str(guild_id), {}).get("batches", [])

    for batch in batches:
        if batch.get("id") == batch_id:
            batch["deleted_at"] = discord.utils.utcnow().isoformat()
            batch["deleted_by"] = deleted_by
            batch["deleted_count"] = deleted_count
            batch["failed_count"] = failed_count
            save_broadcast_history(history)
            return


def build_broadcast_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📢 Central de Disparo de Mensagens",
        description=(
            "Painel administrativo para envio de comunicados em massa para as "
            "pastas privadas dos membros.\n\n"
            "Use este painel para enviar cobranças, lembretes de farm, avisos de "
            "meta semanal e outros comunicados importantes de forma rápida e "
            "automatizada."
        ),
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="⚡ Função",
        value="Envia uma mensagem personalizada para todos os canais válidos da categoria configurada.",
        inline=False,
    )
    embed.add_field(
        name="🎯 Destino",
        value="Somente pastas privadas de membros com nome e ID do game.",
        inline=False,
    )
    embed.add_field(
        name="🚫 Ignora Automaticamente",
        value="Canais livres, tutoriais, avisos, fichas, divisores visuais e painéis administrativos.",
        inline=False,
    )
    embed.add_field(
        name="🔓 Permissão",
        value="Qualquer membro com acesso a este painel pode utilizá-lo.",
        inline=False,
    )
    embed.set_footer(text="Morro do Mineiro • Sistema Administrativo")
    return embed


class BroadcastModal(discord.ui.Modal, title="Disparo de Mensagem Global"):
    mensagem = discord.ui.TextInput(
        label="Mensagem",
        placeholder="Digite a mensagem que será enviada para todas as pastas privadas dos membros.",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Este painel só pode ser usado dentro de um servidor.",
                ephemeral=True,
            )
            return

        category = interaction.guild.get_channel(BROADCAST_CATEGORY_ID)
        if category is None:
            try:
                category = await interaction.guild.fetch_channel(BROADCAST_CATEGORY_ID)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                log.warning("Categoria de destino não encontrada: %s", exc)
                await interaction.response.send_message(
                    "❌ Categoria de destino não encontrada.",
                    ephemeral=True,
                )
                return

        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                "❌ Categoria de destino não encontrada.",
                ephemeral=True,
            )
            log.warning("BROADCAST_CATEGORY_ID=%s não é uma categoria.", BROADCAST_CATEGORY_ID)
            return

        valid_channels = [
            channel for channel in category.channels if is_valid_member_channel(channel)
        ]

        if not valid_channels:
            await interaction.response.send_message(
                "⚠️ Nenhum canal válido encontrado para envio.",
                ephemeral=True,
            )
            log.info(
                "Nenhum canal válido encontrado para disparo (guild=%s, categoria=%s, usuario=%s).",
                interaction.guild.id,
                BROADCAST_CATEGORY_ID,
                interaction.user.id,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        sent_count = 0
        sent_messages: list[dict[str, int]] = []
        message_text = str(self.mensagem.value)

        for channel in valid_channels:
            try:
                bot_member = interaction.guild.me
                if bot_member is None:
                    log.warning("Disparo interrompido: membro do bot não encontrado no servidor.")
                    break

                permissions = channel.permissions_for(bot_member)
                if not permissions.view_channel or not permissions.send_messages:
                    log.warning(
                        "Disparo ignorado sem permissão: #%s (%s)",
                        channel.name,
                        channel.id,
                    )
                    continue

                message = await channel.send(
                    message_text,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                sent_count += 1
                sent_messages.append(
                    {
                        "channel_id": channel.id,
                        "message_id": message.id,
                    }
                )
                log.info("Disparo enviado: #%s (%s)", channel.name, channel.id)
            except (discord.Forbidden, discord.HTTPException) as exc:
                log.warning(
                    "Falha ao enviar disparo para #%s (%s): %s",
                    channel.name,
                    channel.id,
                    exc,
                )
            except Exception as exc:
                log.error(
                    "Erro inesperado ao enviar disparo para #%s (%s): %s",
                    channel.name,
                    channel.id,
                    exc,
                    exc_info=True,
                )

        if sent_messages:
            register_broadcast_batch(interaction.guild.id, interaction.user.id, sent_messages)

        await interaction.followup.send(
            f"✅ Mensagem enviada com sucesso para {sent_count} canais.",
            ephemeral=True,
        )
        log.info(
            "Disparo finalizado por %s (%s): %s/%s canais enviados.",
            interaction.user,
            interaction.user.id,
            sent_count,
            len(valid_channels),
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.error("Erro no BroadcastModal: %s", error, exc_info=True)
        if interaction.response.is_done():
            await interaction.followup.send(
                "❌ Erro interno ao processar o disparo.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "❌ Erro interno ao processar o disparo.",
            ephemeral=True,
        )


class DeleteBroadcastConfirmView(discord.ui.View):
    def __init__(self, batch_id: str, requester_id: int) -> None:
        super().__init__(timeout=60)
        self.batch_id = batch_id
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True

        await interaction.response.send_message(
            "❌ Apenas quem iniciou a exclusão pode confirmar esta ação.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(
        label="Confirmar Exclusão",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
    )
    async def confirm_delete(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Este painel só pode ser usado dentro de um servidor.",
                ephemeral=True,
            )
            return

        batch = get_latest_active_broadcast_batch(interaction.guild.id)
        if batch is None or batch.get("id") != self.batch_id:
            await interaction.response.send_message(
                "⚠️ Este disparo já foi apagado ou não está mais disponível.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        deleted_count = 0
        failed_count = 0
        messages = batch.get("messages", [])

        for item in messages:
            channel_id = item.get("channel_id")
            message_id = item.get("message_id")

            if not channel_id or not message_id:
                failed_count += 1
                continue

            channel = interaction.guild.get_channel(int(channel_id))
            if channel is None:
                try:
                    fetched_channel = await interaction.guild.fetch_channel(int(channel_id))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                    failed_count += 1
                    log.warning("Falha ao buscar canal %s para exclusão: %s", channel_id, exc)
                    continue
                channel = fetched_channel

            if not is_valid_member_channel(channel):
                failed_count += 1
                log.warning("Exclusão ignorada fora dos critérios: canal=%s", channel_id)
                continue

            try:
                message = await channel.fetch_message(int(message_id))
                await message.delete()
                deleted_count += 1
                log.info(
                    "Mensagem de disparo apagada: #%s (%s), mensagem=%s",
                    channel.name,
                    channel.id,
                    message_id,
                )
            except discord.NotFound:
                log.info(
                    "Mensagem de disparo já não existe: canal=%s, mensagem=%s",
                    channel_id,
                    message_id,
                )
            except (discord.Forbidden, discord.HTTPException) as exc:
                failed_count += 1
                log.warning(
                    "Falha ao apagar mensagem de disparo em #%s (%s): %s",
                    channel.name,
                    channel.id,
                    exc,
                )
            except Exception as exc:
                failed_count += 1
                log.error(
                    "Erro inesperado ao apagar mensagem de disparo no canal %s: %s",
                    channel_id,
                    exc,
                    exc_info=True,
                )

        mark_broadcast_batch_deleted(
            interaction.guild.id,
            self.batch_id,
            interaction.user.id,
            deleted_count,
            failed_count,
        )

        await interaction.followup.send(
            f"✅ Mensagens apagadas: {deleted_count}. Falhas: {failed_count}.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Cancelar",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel_delete(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="Exclusão cancelada.",
            view=None,
        )


class BroadcastView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Enviar Mensagem",
        emoji="📨",
        style=discord.ButtonStyle.primary,
        custom_id="broadcast_message_button",
    )
    async def send_message_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(BroadcastModal())

    @discord.ui.button(
        label="Deletar Último Disparo",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        custom_id="broadcast_delete_last_button",
    )
    async def delete_last_broadcast_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Este painel só pode ser usado dentro de um servidor.",
                ephemeral=True,
            )
            return

        batch = get_latest_active_broadcast_batch(interaction.guild.id)
        if batch is None:
            await interaction.response.send_message(
                "⚠️ Nenhum disparo registrado para apagar.",
                ephemeral=True,
            )
            return

        message_count = len(batch.get("messages", []))
        await interaction.response.send_message(
            (
                f"⚠️ Você está prestes a apagar {message_count} mensagens do último disparo.\n"
                "Somente mensagens registradas pelo painel serão removidas."
            ),
            view=DeleteBroadcastConfirmView(
                batch_id=str(batch["id"]),
                requester_id=interaction.user.id,
            ),
            ephemeral=True,
        )


class DisparoCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.add_view(BroadcastView())

    @app_commands.command(
        name="painel_disparo",
        description="Posta o painel administrativo de disparo de mensagens.",
    )
    @app_commands.guild_only()
    async def painel_disparo(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=build_broadcast_embed(),
            view=BroadcastView(),
        )
        log.info(
            "Painel de disparo postado por %s (%s) no canal %s.",
            interaction.user,
            interaction.user.id,
            interaction.channel_id,
        )

    @painel_disparo.error
    async def painel_disparo_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        log.error("Erro em /painel_disparo: %s", error, exc_info=True)
        if interaction.response.is_done():
            await interaction.followup.send("❌ Erro inesperado.", ephemeral=True)
            return

        await interaction.response.send_message("❌ Erro inesperado.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DisparoCog(bot))
    log.info("DisparoCog carregado com sucesso.")
