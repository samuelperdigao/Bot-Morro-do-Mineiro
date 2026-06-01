"""
services/set_service.py - Lógica de pastas privadas: criar, liberar, numeração.

channel_map migrado de JSON para SQLite (db_channel_map_*).
Funções agora recebem private_cat_id e approver_role_ids como parâmetro
em vez de ler do config estático.
"""

import asyncio
import logging

import discord

from services.db_service import (
    db_channel_map_get,
    db_channel_map_delete,
)

# Lock global para evitar race condition na numeração de pastas
_pasta_lock = asyncio.Lock()

# Último número atribuído por categoria — evita duplicação quando o cache
# da guild ainda não recebeu o CHANNEL_CREATE via gateway.
_ultimo_numero: dict[int, int] = {}

log = logging.getLogger("bot")
SEPARADOR_PASTA = "┃"
MAX_CHANNEL_NAME_LENGTH = 100


# ── Helpers de nome ───────────────────────────────────────────────────────────

def safe_channel_name(text: str) -> str:
    return "".join(
        c if c.isalnum() or c in "-_" else "-"
        for c in text.lower().replace(" ", "-")
    ).strip("-")[:50]


def nome_sem_separador(nome: str) -> str:
    return nome[len(SEPARADOR_PASTA):] if nome.startswith(SEPARADOR_PASTA) else nome


def numero_da_pasta(nome: str) -> int | None:
    numero = nome_sem_separador(nome).split("-", 1)[0]
    return int(numero) if numero.isdigit() else None


def montar_nome_pasta(numero: int | str, sufixo: str) -> str:
    return f"{SEPARADOR_PASTA}{numero}-{sufixo}"[:MAX_CHANNEL_NAME_LENGTH]


# ── Helpers de canal ──────────────────────────────────────────────────────────

async def safe_fetch_channel(guild: discord.Guild, channel_id: int):
    try:
        return await guild.fetch_channel(channel_id)
    except Exception as e:
        log.warning(f"Não foi possível buscar canal {channel_id}: {e}")
        return None


# ── Numeração de pastas ───────────────────────────────────────────────────────

async def limpar_mensagens_pasta(canal: discord.TextChannel, motivo: str) -> int:
    """Remove todo o historico visivel de uma pasta privada."""
    total = 0
    try:
        deleted = await canal.purge(limit=None, bulk=False, reason=motivo)
        total = len(deleted)
        log.info("Pasta limpa: %s mensagem(ns) removida(s) em %s (%s)", total, canal.name, canal.id)
    except discord.Forbidden:
        log.warning("Sem permissao para limpar mensagens da pasta %s (%s)", canal.name, canal.id)
    except Exception as e:
        log.error("Erro ao limpar mensagens da pasta %s (%s): %s", canal.name, canal.id, e)
    return total


def proximo_numero_pasta(guild: discord.Guild, private_cat_id: int) -> int:
    category = guild.get_channel(private_cat_id)
    maior = _ultimo_numero.get(private_cat_id, 0)
    if category and hasattr(category, "channels"):
        for ch in category.channels:
            numero = numero_da_pasta(ch.name)
            if numero is not None and numero > maior:
                maior = numero
    proximo = maior + 1
    _ultimo_numero[private_cat_id] = proximo
    return proximo


def encontrar_pasta_livre(guild: discord.Guild, private_cat_id: int) -> discord.TextChannel | None:
    category = guild.get_channel(private_cat_id)
    if not category or not hasattr(category, "channels"):
        return None
    livres = []
    for ch in category.channels:
        numero = numero_da_pasta(ch.name)
        if numero is not None and nome_sem_separador(ch.name).endswith("-livre"):
            livres.append((numero, ch))
    if not livres:
        return None
    livres.sort(key=lambda x: x[0])
    return livres[0][1]


# ── Criação / reutilização de pasta ───────────────────────────────────────────

async def criar_pasta(
    guild: discord.Guild,
    member: discord.Member,
    approver: discord.Member,
    private_cat_id: int,
    approver_role_ids: list[int],
    id_jogo: str = "",
    membro_nome: str = "",
) -> discord.TextChannel | None:
    category = guild.get_channel(private_cat_id)
    if not category:
        try:
            category = await guild.fetch_channel(private_cat_id)
        except Exception as e:
            log.error(f"Categoria {private_cat_id} não encontrada: {e}")
            return None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
        ),
    }
    for role_id in approver_role_ids:
        role = guild.get_role(role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

    safe_name = safe_channel_name(membro_nome or member.display_name)
    sufixo    = f"-{id_jogo}" if id_jogo else ""

    async with _pasta_lock:
        pasta_livre = encontrar_pasta_livre(guild, private_cat_id)

        if pasta_livre:
            numero    = numero_da_pasta(pasta_livre.name)
            novo_nome = montar_nome_pasta(numero, f"{safe_name}{sufixo}")
            try:
                await pasta_livre.edit(
                    name=novo_nome,
                    overwrites=overwrites,
                    reason=f"Pasta reutilizada — Set aprovado por {approver}",
                )
                log.info(f"Pasta reutilizada: {pasta_livre.name} → {novo_nome} ({pasta_livre.id})")
                return pasta_livre
            except Exception as e:
                log.error(f"Erro ao reutilizar pasta livre: {e}")

        numero       = proximo_numero_pasta(guild, private_cat_id)
        channel_name = montar_nome_pasta(numero, f"{safe_name}{sufixo}")
        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Set aprovado por {approver}",
            )
            log.info(f"Canal privado criado: {channel.name} ({channel.id})")
            return channel
        except Exception as e:
            log.error(f"Erro ao criar canal privado: {e}")
            return None


# ── Liberação de pasta ao membro sair ─────────────────────────────────────────

async def liberar_pasta(
    guild: discord.Guild,
    member: discord.Member | None,
    guild_id: str,
    user_id: str | None = None,
    limpar_mensagens: bool = True,
) -> bool:
    """
    Libera a pasta privada de um membro.

    Pode ser chamada com `member` (evento normal) ou apenas `user_id`
    (reconciliacao pos-restart, quando o membro ja nao esta no servidor).
    """
    uid = user_id if user_id else str(member.id)
    ch_id = db_channel_map_get(guild_id, uid)
    if not ch_id:
        return False

    canal = guild.get_channel(ch_id) or await safe_fetch_channel(guild, ch_id)
    if not canal:
        db_channel_map_delete(guild_id, uid)
        return False

    async with _pasta_lock:
        numero = numero_da_pasta(canal.name)
        if numero is not None:
            novo_nome = montar_nome_pasta(numero, "livre")
        else:
            novo_nome = f"{SEPARADOR_PASTA}{nome_sem_separador(canal.name)}-livre"[:MAX_CHANNEL_NAME_LENGTH]

        try:
            overwrites = dict(canal.overwrites)
            overwrites.pop(discord.Object(id=int(uid)), None)
            if member:
                overwrites.pop(member, None)
            razao = f"Membro {member or uid} saiu do servidor"
            nome_antigo = canal.name
            await canal.edit(name=novo_nome, overwrites=overwrites, reason=razao)
            log.info("Pasta liberada: %s -> %s (%s)", nome_antigo, novo_nome, canal.id)
        except Exception as e:
            log.error("Erro ao liberar pasta de %s: %s", uid, e)
            return False

        if limpar_mensagens:
            await limpar_mensagens_pasta(canal, f"Limpeza automatica apos saida do membro {member or uid}")

    db_channel_map_delete(guild_id, uid)
    return True
