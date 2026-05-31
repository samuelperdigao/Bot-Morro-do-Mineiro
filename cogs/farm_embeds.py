"""Builders de embeds do sistema de farm."""

import discord

from services.db_service import (
    CLASSIFICACAO_LABEL,
    DINHEIRO_ITEMS,
    DINHEIRO_LIMPO_ITEM,
    DINHEIRO_SUJO_ITEM,
    db_meta_dinheiro_ativo,
    db_meta_dinheiro_itens_ativos,
    db_meta_itens_ativos,
    db_meta_tipo_efetivo,
    db_get_meta,
    db_prog_itens,
    fmt_dt,
    janela_valida,
)

FARM_PRODUTOS = [
    ("Borracha", "🛞"),
    ("Aluminio", "⚙️"),
    ("Cobre", "🔶"),
    ("Plastico", "🧴"),
]


def _progress_bar(pct: float, length: int = 10) -> str:
    filled = int(min(pct, 100) / 100 * length)
    return "█" * filled + "░" * (length - filled)


def _status_emoji(pct: float) -> str:
    if pct >= 100:
        return "✅"
    if pct >= 50:
        return "🟡"
    return "🔴"


def _pct_produto(prog_val: int | float, meta_val: int | float) -> float:
    return (prog_val / meta_val * 100) if meta_val > 0 else 0.0


def build_farm_embed(meta, prog, member: discord.Member, week_id: str) -> discord.Embed:
    aprovada = bool(prog and prog["aprovada"])
    antecipada = bool(prog and prog["aprovacao_antecipada"])
    meta_tipo = db_meta_tipo_efetivo(meta)
    meta_itens = db_meta_itens_ativos(meta)
    meta_dinheiro_itens = db_meta_dinheiro_itens_ativos(meta)
    prog_itens = db_prog_itens(prog)
    meta_valor = db_meta_dinheiro_ativo(meta)

    if meta_tipo == "dinheiro" and meta_valor > 0:
        if meta_dinheiro_itens:
            concluida_ativa = all(
                prog_itens.get(nome, 0) >= meta_val
                for nome, meta_val in meta_dinheiro_itens.items()
                if meta_val > 0
            )
        else:
            total_dinheiro = sum(prog_itens.get(nome, 0) for nome in DINHEIRO_ITEMS)
            concluida_ativa = total_dinheiro >= meta_valor
    elif meta_itens:
        concluida_ativa = all(
            prog_itens.get(nome, 0) >= meta_val
            for nome, meta_val in meta_itens.items()
            if meta_val > 0
        )
    else:
        concluida_ativa = False
    status_label = "concluida" if concluida_ativa else "em_andamento"

    if aprovada:
        color = discord.Color.gold()
    elif status_label == "concluida":
        color = discord.Color.green()
    else:
        color = discord.Color.blue()

    embed = discord.Embed(
        title=f"🌿 Farm — {member.display_name}",
        description=f"📅 Semana: `{week_id}`",
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    if meta_itens:
        for nome, meta_val in meta_itens.items():
            prog_val = prog_itens.get(nome, 0)
            pct = _pct_produto(prog_val, meta_val)
            embed.add_field(
                name=f"{_status_emoji(pct)} {nome}",
                value=f"{_progress_bar(pct)}\n`{prog_val}` / `{meta_val}` — **{pct:.0f}%**",
                inline=True,
            )

    if meta_dinheiro_itens:
        for nome, meta_item_val in meta_dinheiro_itens.items():
            prog_item_val = prog_itens.get(nome, 0)
            pct = _pct_produto(prog_item_val, meta_item_val)
            meta_fmt = f"R$ {meta_item_val:,.0f}".replace(",", ".")
            prog_fmt = f"R$ {prog_item_val:,.0f}".replace(",", ".")
            embed.add_field(
                name=f"{_status_emoji(pct)} 💵 {nome}",
                value=f"{_progress_bar(pct)}\n`{prog_fmt}` / `{meta_fmt}` — **{pct:.0f}%**",
                inline=True,
            )

    elif meta_valor > 0:
        sujo = prog_itens.get(DINHEIRO_SUJO_ITEM, 0)
        limpo = prog_itens.get(DINHEIRO_LIMPO_ITEM, 0)
        prog_valor = sum(prog_itens.get(nome, 0) for nome in DINHEIRO_ITEMS)
        pct = _pct_produto(prog_valor, meta_valor) if meta_valor else 0
        meta_fmt = f"R$ {meta_valor:,.0f}".replace(",", ".")
        prog_fmt = f"R$ {prog_valor:,.0f}".replace(",", ".")
        sujo_fmt = f"R$ {sujo:,.0f}".replace(",", ".")
        limpo_fmt = f"R$ {limpo:,.0f}".replace(",", ".")
        embed.add_field(
            name=f"{_status_emoji(pct)} 💵 Dinheiro",
            value=(
                f"{_progress_bar(pct)}\n"
                f"`{prog_fmt}` / `{meta_fmt}` — **{pct:.0f}%**\n"
                f"Sujo: `{sujo_fmt}` | Limpo: `{limpo_fmt}`"
            ),
            inline=False,
        )

    if not meta_itens and meta_valor <= 0:
        embed.add_field(
            name="⚠️ Sem meta definida",
            value="A liderança ainda não definiu as metas da semana.",
            inline=False,
        )

    embed.add_field(name="\u200b", value="\u200b", inline=False)
    status_map = {"em_andamento": "🔄 Em andamento", "concluida": "✅ Concluída"}
    status_txt = status_map.get(status_label, "🔄 Em andamento")

    if aprovada and antecipada:
        aprov_txt = "⚡ Aprovação antecipada"
    elif aprovada:
        aprov_txt = "🏆 Aprovada pela liderança"
    else:
        aprov_txt = "⏳ Aguardando aprovação"

    ultimo = fmt_dt(prog["ultimo_lancamento_em"] if prog else None)
    embed.add_field(name="Status", value=status_txt, inline=True)
    embed.add_field(name="Aprovação", value=aprov_txt, inline=True)
    embed.add_field(name="Último lançamento", value=f"`{ultimo}`", inline=True)

    footer = "⚠️ Fora da janela de lançamento (Seg-Dom) • Atualizado" if not janela_valida() else "Atualizado"
    embed.set_footer(text=footer)
    return embed


def build_meta_embed(meta, week_id: str) -> discord.Embed:
    embed = discord.Embed(
        title="🎯 Metas da Semana",
        description=f"📅 Semana: `{week_id}`",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow(),
    )
    if meta:
        itens = db_meta_itens_ativos(meta)
        if itens:
            for nome, qtd in itens.items():
                embed.add_field(name=nome, value=f"`{qtd}`", inline=True)
        valor = db_meta_dinheiro_ativo(meta)
        dinheiro_itens = db_meta_dinheiro_itens_ativos(meta)
        if dinheiro_itens:
            for nome, qtd in dinheiro_itens.items():
                embed.add_field(
                    name=f"💵 {nome}",
                    value=f"**R$ {qtd:,.0f}**".replace(",", "."),
                    inline=True,
                )
        elif valor > 0:
            embed.add_field(name="💵 Dinheiro", value=f"**R$ {valor:,.0f}**".replace(",", "."), inline=False)
        if not itens and valor <= 0:
            embed.add_field(name="⚠️ Metas não definidas", value="Use o botão abaixo para definir.", inline=False)
        embed.set_footer(text=f"Definido por ID {meta['definido_por']} • {fmt_dt(meta['definido_em'])}")
    else:
        embed.add_field(name="⚠️ Metas não definidas", value="Use o botão abaixo para definir.", inline=False)
    return embed


def build_ranking_embed(guild_id: str, week_id: str, participantes: list, guild: discord.Guild) -> discord.Embed:
    meta = db_get_meta(guild_id, week_id)
    meta_tipo = db_meta_tipo_efetivo(meta)
    embed = discord.Embed(
        title="🏆 Ranking da Semana",
        description=f"📅 Semana: `{week_id}`",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow(),
    )
    medalhas = ["🥇", "🥈", "🥉"]
    linhas = []
    for i, row in enumerate(participantes[:10]):
        medalha = medalhas[i] if i < 3 else f"`#{i + 1}`"
        member = guild.get_member(int(row["user_id"]))
        nome = member.display_name if member else f"ID {row['user_id']}"
        pct = row.get("pct", 0) if isinstance(row, dict) else (row["pct"] if "pct" in row.keys() else 0)
        total = row.get("total", 0) if isinstance(row, dict) else 0
        total_txt = f"R$ {total:,.0f}".replace(",", ".") if meta_tipo == "dinheiro" else f"{total:,.0f}".replace(",", ".")
        classificacao = row.get("classificacao", "zero") if isinstance(row, dict) else "zero"
        label = CLASSIFICACAO_LABEL.get(classificacao, "❌ Zero")
        linhas.append(f"{medalha} **{nome}** — {pct:.0f}% · {total_txt} · {label}")

    embed.description += "\n\n" + ("\n".join(linhas) if linhas else "Nenhum participante ainda.")
    embed.set_footer(text="Ranking acompanha a meta escolhida da semana")
    return embed
