"""Painel rapido e inteligente do Bau da Gerencia."""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from cogs.bau_core import (
    CATEGORIAS,
    BauRepository,
    DuplicateOperationError,
    MovementLine,
    OperationResult,
    StaleOperationError,
    StockInsufficientError,
    UndoOperation,
    UndoResult,
    agora_str,
    parse_batch_text,
)
from core.logger import get_logger


log = get_logger("bau", "bau.log")

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "bau.db"
PAINEL_JSON = BASE_DIR / "bau_painel.json"

CANAL_BAU_ID = 1474869322387292357
CANAL_LOG_ID = 1499589255784173678

PREVIEW_PAGE_SIZE = 15
UNDO_PAGE_SIZE = 25
repo = BauRepository(DB_PATH)


def _load_painel_ref() -> tuple[int | None, int | None]:
    if PAINEL_JSON.exists():
        try:
            data = json.loads(PAINEL_JSON.read_text(encoding="utf-8"))
            return int(data["channel_id"]), int(data["message_id"])
        except Exception as exc:
            log.warning("Erro ao ler bau_painel.json: %s", exc)
    return None, None


def _save_painel_ref(channel_id: int, message_id: int) -> None:
    PAINEL_JSON.write_text(
        json.dumps({"channel_id": channel_id, "message_id": message_id}),
        encoding="utf-8",
    )


def _format_number(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _movement_label(movement_type: str) -> str:
    return "Entrada" if movement_type == "entrada" else "Retirada"


def _origin_label(origin: str) -> str:
    return {
        "rapido": "Movimentacao rapida",
        "personalizado": "Quantidade personalizada",
        "lote": "Movimentacao em lote",
        "individual": "Movimentacao individual",
    }.get(origin, origin.title())


def _build_painel_embed() -> discord.Embed:
    stock = repo.get_stock()
    embed = discord.Embed(
        title="\U0001f3e6 Bau da Gerencia",
        description=(
            "Selecione uma categoria ou use os botoes para movimentacoes em lote, "
            "desfazer e zerar o estoque."
        ),
        color=discord.Color.dark_gold(),
    )
    has_items = False
    for category, products in CATEGORIAS.items():
        lines = [
            f"\u2022 {product}: **{_format_number(stock.get(product, 0))}**"
            for product in products
            if stock.get(product, 0) > 0
        ]
        if lines:
            embed.add_field(name=category, value="\n".join(lines), inline=True)
            has_items = True
    if not has_items:
        embed.description = (
            "*Nenhum item no bau no momento.*\n\n"
            "Use o seletor ou os botoes de entrada para iniciar a atualizacao."
        )
    embed.set_footer(text=f"Ultima atualizacao: {agora_str()} (Brasilia)")
    return embed


def _build_preview_embed(
    movement_type: str,
    items: list[tuple[str, int]],
    page: int,
    origin: str,
) -> discord.Embed:
    stock = repo.get_stock()
    total_pages = max(1, math.ceil(len(items) / PREVIEW_PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    start = page * PREVIEW_PAGE_SIZE
    page_items = items[start:start + PREVIEW_PAGE_SIZE]
    sign = 1 if movement_type == "entrada" else -1
    color = discord.Color.green() if sign == 1 else discord.Color.red()
    embed = discord.Embed(
        title=f"Confirmar {_movement_label(movement_type)}",
        description=(
            f"Origem: **{_origin_label(origin)}**\n"
            "Confira o estoque antes e depois. Nada foi alterado ainda."
        ),
        color=color,
    )
    for product, quantity in page_items:
        before = stock.get(product, 0)
        after = before + (sign * quantity)
        warning = " \u26a0\ufe0f" if after < 0 else ""
        embed.add_field(
            name=product,
            value=(
                f"Quantidade: **{_format_number(quantity)}**\n"
                f"`{_format_number(before)} -> {_format_number(after)}`{warning}"
            ),
            inline=True,
        )
    embed.set_footer(
        text=f"Pagina {page + 1}/{total_pages} | {len(items)} produto(s)"
    )
    return embed


def _build_parse_error_embed(issues) -> discord.Embed:
    embed = discord.Embed(
        title="\u274c Lote nao reconhecido",
        description=(
            "Corrija as linhas abaixo e abra o lote novamente. "
            "Nenhum produto foi movimentado."
        ),
        color=discord.Color.red(),
    )
    lines = []
    for issue in issues[:15]:
        prefix = f"Linha {issue.line_number}" if issue.line_number else "Lote"
        detail = f"**{prefix}:** {issue.message}"
        if issue.raw_line:
            detail += f"\n`{issue.raw_line[:120]}`"
        if issue.suggestions:
            detail += "\nSugestao: " + ", ".join(
                f"`{suggestion}`" for suggestion in issue.suggestions
            )
        lines.append(detail)
    embed.description = (embed.description + "\n\n" + "\n\n".join(lines))[:4096]
    if len(issues) > 15:
        embed.set_footer(text=f"Mais {len(issues) - 15} erro(s) nao exibido(s).")
    return embed


def _chunk_lines(lines: tuple[MovementLine, ...], size: int = 20):
    for index in range(0, len(lines), size):
        yield lines[index:index + size]


def _build_operation_log_embeds(
    result: OperationResult,
    user: discord.abc.User,
) -> list[discord.Embed]:
    chunks = list(_chunk_lines(result.lines))
    embeds: list[discord.Embed] = []
    sign = "+" if result.tipo == "entrada" else "-"
    color = discord.Color.green() if result.tipo == "entrada" else discord.Color.red()
    for page, chunk in enumerate(chunks, start=1):
        embed = discord.Embed(
            title=f"{_movement_label(result.tipo)} no Bau",
            color=color,
        )
        if page == 1:
            embed.description = (
                f"Usuario: **{user.display_name}** (`{user.id}`)\n"
                f"Origem: **{_origin_label(result.origem)}**\n"
                f"Operacao: `{result.operation_id}`"
            )
        for line in chunk:
            embed.add_field(
                name=line.produto,
                value=(
                    f"{sign}{_format_number(line.quantidade)}\n"
                    f"`{_format_number(line.estoque_antes)} -> "
                    f"{_format_number(line.estoque_depois)}`"
                ),
                inline=True,
            )
        embed.set_footer(
            text=f"{result.criado_em} | Pagina {page}/{len(chunks)}"
        )
        embeds.append(embed)
    return embeds


def _build_undo_log_embeds(
    result: UndoResult,
    user: discord.abc.User,
) -> list[discord.Embed]:
    reverted = result.reverted
    embeds: list[discord.Embed] = []
    if reverted:
        chunks = list(_chunk_lines(reverted))
        for page, chunk in enumerate(chunks, start=1):
            embed = discord.Embed(
                title="\u21a9\ufe0f Movimentacao desfeita",
                color=discord.Color.orange(),
            )
            if page == 1:
                embed.description = (
                    f"Usuario: **{user.display_name}** (`{user.id}`)\n"
                    f"Operacao original: `{result.operation_id}`"
                )
            for line in chunk:
                embed.add_field(
                    name=line.produto,
                    value=(
                        f"Revertido: **{_format_number(line.quantidade)}**\n"
                        f"`{_format_number(line.estoque_antes)} -> "
                        f"{_format_number(line.estoque_depois)}`"
                    ),
                    inline=True,
                )
            embed.set_footer(text=f"Pagina {page}/{len(chunks)}")
            embeds.append(embed)
    if result.skipped:
        skipped_lines = [
            f"\u2022 {product}: precisa {_format_number(quantity)}, "
            f"disponivel {_format_number(available)}"
            for product, quantity, available in result.skipped
        ]
        skipped_chunks = [
            skipped_lines[index:index + 25]
            for index in range(0, len(skipped_lines), 25)
        ]
        for page, chunk in enumerate(skipped_chunks, start=1):
            embed = discord.Embed(
                title="\u26a0\ufe0f Itens nao desfeitos",
                description="\n".join(chunk),
                color=discord.Color.gold(),
            )
            embed.set_footer(
                text=f"Pagina {page}/{len(skipped_chunks)}"
            )
            embeds.append(embed)
    return embeds


async def _send_log(
    client: discord.Client,
    embeds: list[discord.Embed],
) -> None:
    if not embeds:
        return
    channel = client.get_channel(CANAL_LOG_ID)
    if channel is None:
        try:
            channel = await client.fetch_channel(CANAL_LOG_ID)
        except Exception:
            channel = None
    if channel is None:
        log.warning("Canal de log do bau nao encontrado: %s", CANAL_LOG_ID)
        return
    try:
        for start in range(0, len(embeds), 10):
            await channel.send(embeds=embeds[start:start + 10])
    except Exception:
        log.error("Erro ao enviar log do bau.", exc_info=True)


async def _refresh_panel(client: discord.Client) -> None:
    cog = client.get_cog("BauCog")
    if cog:
        await cog.atualizar_painel()


class RequesterView(discord.ui.View):
    def __init__(self, requester_id: int, timeout: float = 180) -> None:
        super().__init__(timeout=timeout)
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message(
            "\u274c Apenas quem iniciou esta acao pode continua-la.",
            ephemeral=True,
        )
        return False


class MovementConfirmView(RequesterView):
    def __init__(
        self,
        movement_type: str,
        items: list[tuple[str, int]],
        origin: str,
        requester_id: int,
        operation_id: str | None = None,
    ) -> None:
        super().__init__(requester_id)
        self.movement_type = movement_type
        self.items = items
        self.origin = origin
        self.operation_id = operation_id or uuid.uuid4().hex
        self.generation = repo.get_generation()
        self.page = 0
        self.total_pages = max(1, math.ceil(len(items) / PREVIEW_PAGE_SIZE))
        self._sync_buttons()

    def embed(self) -> discord.Embed:
        return _build_preview_embed(
            self.movement_type,
            self.items,
            self.page,
            self.origin,
        )

    def _sync_buttons(self) -> None:
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page >= self.total_pages - 1

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.secondary, row=0)
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.page -= 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Proxima", style=discord.ButtonStyle.secondary, row=0)
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.page += 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(
        label="Confirmar",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="Processando movimentacao...",
            embed=None,
            view=None,
        )
        try:
            result = repo.apply_operation(
                self.movement_type,
                self.items,
                str(interaction.user.id),
                interaction.user.display_name,
                self.origin,
                self.operation_id,
                self.generation,
            )
        except StockInsufficientError as exc:
            shortages = "\n".join(
                f"\u2022 **{product}**: solicitado {_format_number(requested)}, "
                f"disponivel {_format_number(available)}"
                for product, (requested, available) in exc.shortages.items()
            )
            await interaction.edit_original_response(
                content=None,
                embed=discord.Embed(
                    title="\u274c Estoque insuficiente",
                    description=(
                        "A operacao inteira foi cancelada. Nenhum item foi alterado.\n\n"
                        + shortages
                    ),
                    color=discord.Color.red(),
                ),
                view=None,
            )
            return
        except DuplicateOperationError:
            await interaction.edit_original_response(
                content="\u26a0\ufe0f Esta operacao ja foi processada.",
                embed=None,
                view=None,
            )
            return
        except StaleOperationError:
            await interaction.edit_original_response(
                content=(
                    "\u26a0\ufe0f O bau foi zerado depois que esta confirmacao "
                    "foi aberta. Abra uma nova movimentacao."
                ),
                embed=None,
                view=None,
            )
            return
        except Exception:
            log.error("Erro ao movimentar o bau.", exc_info=True)
            await interaction.edit_original_response(
                content="\u274c Erro ao registrar a movimentacao.",
                embed=None,
                view=None,
            )
            return

        await _refresh_panel(interaction.client)
        await _send_log(
            interaction.client,
            _build_operation_log_embeds(result, interaction.user),
        )
        await interaction.edit_original_response(
            content=None,
            embed=discord.Embed(
                title="\u2705 Movimentacao registrada",
                description=(
                    f"**{_movement_label(result.tipo)}** concluida para "
                    f"**{len(result.lines)} produto(s)**.\n"
                    f"Operacao: `{result.operation_id}`"
                ),
                color=discord.Color.green(),
            ),
            view=None,
        )
        self.stop()

    @discord.ui.button(
        label="Cancelar",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="Movimentacao cancelada. Nenhum item foi alterado.",
            embed=None,
            view=None,
        )
        self.stop()


class CustomQuantityModal(discord.ui.Modal):
    quantity = discord.ui.TextInput(
        label="Quantidade",
        placeholder="Ex: 1000",
        min_length=1,
        max_length=12,
        required=True,
    )

    def __init__(self, movement_type: str, product: str) -> None:
        super().__init__(
            title=f"{_movement_label(movement_type)} - {product}"[:45]
        )
        self.movement_type = movement_type
        self.product = product

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.quantity.value).strip()
        if not raw.isdigit() or int(raw) <= 0:
            await interaction.response.send_message(
                "\u274c Digite um numero inteiro positivo maior que zero.",
                ephemeral=True,
            )
            return
        view = MovementConfirmView(
            self.movement_type,
            [(self.product, int(raw))],
            "personalizado",
            interaction.user.id,
        )
        await interaction.response.send_message(
            embed=view.embed(),
            view=view,
            ephemeral=True,
        )


class ProductActionView(RequesterView):
    def __init__(self, product: str, requester_id: int) -> None:
        super().__init__(requester_id, timeout=180)
        self.product = product
        for row, movement_type in enumerate(("entrada", "saida")):
            prefix = "+" if movement_type == "entrada" else "-"
            style = (
                discord.ButtonStyle.success
                if movement_type == "entrada"
                else discord.ButtonStyle.danger
            )
            for quantity in (1, 10, 50, 100):
                button = discord.ui.Button(
                    label=f"{prefix}{quantity}",
                    style=style,
                    row=row,
                )
                button.callback = self._quick_callback(movement_type, quantity)
                self.add_item(button)

        entry_custom = discord.ui.Button(
            label="+ Personalizado",
            style=discord.ButtonStyle.success,
            row=2,
        )
        entry_custom.callback = self._custom_callback("entrada")
        self.add_item(entry_custom)
        exit_custom = discord.ui.Button(
            label="- Personalizado",
            style=discord.ButtonStyle.danger,
            row=2,
        )
        exit_custom.callback = self._custom_callback("saida")
        self.add_item(exit_custom)

    def _quick_callback(self, movement_type: str, quantity: int):
        async def callback(interaction: discord.Interaction) -> None:
            view = MovementConfirmView(
                movement_type,
                [(self.product, quantity)],
                "rapido",
                interaction.user.id,
            )
            await interaction.response.edit_message(
                content=None,
                embed=view.embed(),
                view=view,
            )
        return callback

    def _custom_callback(self, movement_type: str):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.send_modal(
                CustomQuantityModal(movement_type, self.product)
            )
        return callback


class ProductSelect(discord.ui.Select):
    def __init__(self, products: list[str]) -> None:
        stock = repo.get_stock()
        options = [
            discord.SelectOption(
                label=product,
                value=product,
                description=f"Estoque atual: {_format_number(stock.get(product, 0))}",
            )
            for product in products[:25]
        ]
        super().__init__(
            placeholder="Selecione o produto...",
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        product = self.values[0]
        await interaction.response.edit_message(
            content=f"\U0001f527 **{product}** - escolha a quantidade:",
            embed=None,
            view=ProductActionView(product, interaction.user.id),
        )


class ProductsView(RequesterView):
    def __init__(self, products: list[str], requester_id: int) -> None:
        super().__init__(requester_id, timeout=180)
        self.add_item(ProductSelect(products))


class CategorySelect(discord.ui.Select):
    RECENT = "__recent__"
    FREQUENT = "__frequent__"

    def __init__(self) -> None:
        options = [
            discord.SelectOption(
                label="Usados recentemente",
                value=self.RECENT,
                emoji="\U0001f552",
            ),
            discord.SelectOption(
                label="Mais movimentados",
                value=self.FREQUENT,
                emoji="\u2b50",
            ),
        ]
        options.extend(
            discord.SelectOption(label=category, value=category)
            for category in CATEGORIAS
        )
        super().__init__(
            custom_id="bau:categoria_select",
            placeholder="Selecione categoria, recentes ou favoritos...",
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0]
        if selected == self.RECENT:
            products = repo.get_recent_products()
            title = "\U0001f552 Usados recentemente"
        elif selected == self.FREQUENT:
            products = repo.get_frequent_products()
            title = "\u2b50 Mais movimentados"
        else:
            products = CATEGORIAS[selected]
            title = selected

        if not products:
            await interaction.response.send_message(
                "\u26a0\ufe0f Ainda nao ha movimentacoes para esta lista.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"\U0001f4e6 **{title}** - selecione o produto:",
            view=ProductsView(list(products), interaction.user.id),
            ephemeral=True,
        )


class BatchModal(discord.ui.Modal):
    items_text = discord.ui.TextInput(
        label="Produtos e quantidades",
        placeholder="5mm: 500\nColete: 20\nDinheiro Sujo: 100000",
        style=discord.TextStyle.paragraph,
        min_length=1,
        max_length=4000,
        required=True,
    )

    def __init__(self, movement_type: str) -> None:
        super().__init__(title=f"{_movement_label(movement_type)} em lote")
        self.movement_type = movement_type

    async def on_submit(self, interaction: discord.Interaction) -> None:
        parsed = parse_batch_text(str(self.items_text.value))
        if not parsed.valid:
            await interaction.response.send_message(
                embed=_build_parse_error_embed(parsed.issues),
                ephemeral=True,
            )
            return
        view = MovementConfirmView(
            self.movement_type,
            parsed.items,
            "lote",
            interaction.user.id,
        )
        await interaction.response.send_message(
            embed=view.embed(),
            view=view,
            ephemeral=True,
        )


class UndoProductSelect(discord.ui.Select):
    def __init__(self, parent: "UndoView", page_items: list[tuple[str, int]]) -> None:
        self.parent_view = parent
        options = [
            discord.SelectOption(
                label=product,
                value=product,
                description=f"Quantidade original: {_format_number(quantity)}",
                default=product in parent.selected,
            )
            for product, quantity in page_items
        ]
        super().__init__(
            placeholder="Itens selecionados para desfazer...",
            min_values=1,
            max_values=len(options),
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        page_products = {
            product for product, _ in self.parent_view.page_items()
        }
        self.parent_view.selected.difference_update(page_products)
        self.parent_view.selected.update(self.values)
        self.parent_view.rebuild_select()
        await interaction.response.edit_message(
            embed=self.parent_view.embed(),
            view=self.parent_view,
        )


class UndoView(RequesterView):
    def __init__(self, operation: UndoOperation, requester_id: int) -> None:
        super().__init__(requester_id, timeout=300)
        self.operation = operation
        self.page = 0
        self.total_pages = max(
            1,
            math.ceil(len(operation.items) / UNDO_PAGE_SIZE),
        )
        self.selected = {product for product, _ in operation.items}
        self.rebuild_select()
        self._sync_buttons()

    def page_items(self) -> list[tuple[str, int]]:
        start = self.page * UNDO_PAGE_SIZE
        return list(self.operation.items[start:start + UNDO_PAGE_SIZE])

    def rebuild_select(self) -> None:
        for child in list(self.children):
            if isinstance(child, UndoProductSelect):
                self.remove_item(child)
        self.add_item(UndoProductSelect(self, self.page_items()))

    def _sync_buttons(self) -> None:
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page >= self.total_pages - 1

    def embed(self) -> discord.Embed:
        page_items = self.page_items()
        lines = []
        for product, quantity in page_items:
            marker = "\u2705" if product in self.selected else "\u2b1c"
            lines.append(
                f"{marker} **{product}**: {_format_number(quantity)}"
            )
        return discord.Embed(
            title="\u21a9\ufe0f Desfazer minha ultima movimentacao",
            description=(
                f"Operacao: `{self.operation.operation_id}`\n"
                f"Tipo original: **{_movement_label(self.operation.tipo)}**\n"
                f"Data: **{self.operation.criado_em}**\n\n"
                + "\n".join(lines)
            ),
            color=discord.Color.orange(),
        ).set_footer(
            text=(
                f"Pagina {self.page + 1}/{self.total_pages} | "
                f"{len(self.selected)} item(ns) selecionado(s)"
            )
        )

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.secondary, row=1)
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.page -= 1
        self.rebuild_select()
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Proxima", style=discord.ButtonStyle.secondary, row=1)
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.page += 1
        self.rebuild_select()
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(
        label="Selecionar pagina",
        style=discord.ButtonStyle.primary,
        row=2,
    )
    async def select_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.selected.update(product for product, _ in self.page_items())
        self.rebuild_select()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(
        label="Limpar pagina",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def clear_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.selected.difference_update(product for product, _ in self.page_items())
        self.rebuild_select()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(
        label="Confirmar desfazer",
        style=discord.ButtonStyle.success,
        row=3,
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self.selected:
            await interaction.response.send_message(
                "\u274c Selecione pelo menos um produto.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            content="Desfazendo itens selecionados...",
            embed=None,
            view=None,
        )
        try:
            result = repo.undo_items(
                self.operation.operation_id,
                str(interaction.user.id),
                self.selected,
            )
        except Exception:
            log.error("Erro ao desfazer movimentacao do bau.", exc_info=True)
            await interaction.edit_original_response(
                content="\u274c Nao foi possivel desfazer esta movimentacao.",
                embed=None,
                view=None,
            )
            return

        if result.reverted:
            await _refresh_panel(interaction.client)
        await _send_log(
            interaction.client,
            _build_undo_log_embeds(result, interaction.user),
        )
        reverted_text = (
            f"\u2705 **{len(result.reverted)}** item(ns) desfeito(s)."
            if result.reverted
            else "\u26a0\ufe0f Nenhum item pode ser desfeito."
        )
        skipped_text = (
            f"\n\u26a0\ufe0f **{len(result.skipped)}** item(ns) ignorado(s) "
            "por falta de estoque."
            if result.skipped
            else ""
        )
        await interaction.edit_original_response(
            content=reverted_text + skipped_text,
            embed=None,
            view=None,
        )
        self.stop()

    @discord.ui.button(
        label="Cancelar",
        style=discord.ButtonStyle.danger,
        row=3,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="Desfazer cancelado.",
            embed=None,
            view=None,
        )
        self.stop()


class ClearConfirmView(RequesterView):
    def __init__(self, requester_id: int) -> None:
        super().__init__(requester_id, timeout=60)

    @discord.ui.button(
        label="Confirmar zeragem",
        style=discord.ButtonStyle.danger,
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="Zerando o bau e apagando o historico...",
            embed=None,
            view=None,
        )
        try:
            previous = repo.clear_all()
        except Exception:
            log.error("Erro ao zerar o bau.", exc_info=True)
            await interaction.edit_original_response(
                content="\u274c Nao foi possivel zerar o bau.",
                view=None,
            )
            return

        await _refresh_panel(interaction.client)
        total_units = sum(previous.values())
        log_embed = discord.Embed(
            title="\U0001f5d1\ufe0f Bau zerado por completo",
            description=(
                f"Usuario: **{interaction.user.display_name}** "
                f"(`{interaction.user.id}`)\n"
                f"Produtos que tinham saldo: **{len(previous)}**\n"
                f"Unidades removidas: **{_format_number(total_units)}**\n"
                "O historico anterior, recentes, favoritos e dados de desfazer "
                "foram apagados."
            ),
            color=discord.Color.dark_red(),
        )
        log_embed.set_footer(text=agora_str())
        await _send_log(interaction.client, [log_embed])
        await interaction.edit_original_response(
            content=(
                "\u2705 Bau 100% zerado. Todos os produtos permanecem cadastrados "
                "com quantidade zero e o historico anterior foi apagado."
            ),
            embed=None,
            view=None,
        )
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="Zeragem cancelada. Nada foi alterado.",
            embed=None,
            view=None,
        )
        self.stop()


class BauPainelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(CategorySelect())

    @discord.ui.button(
        label="Entrada em lote",
        emoji="\U0001f4e5",
        style=discord.ButtonStyle.success,
        custom_id="bau:lote_entrada",
        row=1,
    )
    async def batch_entry(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(BatchModal("entrada"))

    @discord.ui.button(
        label="Retirada em lote",
        emoji="\U0001f4e4",
        style=discord.ButtonStyle.danger,
        custom_id="bau:lote_saida",
        row=1,
    )
    async def batch_exit(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(BatchModal("saida"))

    @discord.ui.button(
        label="Desfazer",
        emoji="\u21a9\ufe0f",
        style=discord.ButtonStyle.secondary,
        custom_id="bau:desfazer",
        row=2,
    )
    async def undo(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        operation = repo.get_last_undoable_operation(str(interaction.user.id))
        if operation is None:
            await interaction.response.send_message(
                "\u26a0\ufe0f Voce nao possui movimentacoes disponiveis para desfazer.",
                ephemeral=True,
            )
            return
        view = UndoView(operation, interaction.user.id)
        await interaction.response.send_message(
            embed=view.embed(),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Limpar Bau",
        emoji="\U0001f5d1\ufe0f",
        style=discord.ButtonStyle.danger,
        custom_id="bau:limpar",
        row=2,
    )
    async def clear(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        embed = discord.Embed(
            title="\u26a0\ufe0f Zerar todo o Bau?",
            description=(
                "Esta acao vai:\n"
                "\u2022 definir **todos os 78 produtos como zero**;\n"
                "\u2022 apagar **todo o historico anterior**;\n"
                "\u2022 limpar recentes, favoritos e operacoes para desfazer.\n\n"
                "**Esta acao nao pode ser desfeita.**"
            ),
            color=discord.Color.dark_red(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=ClearConfirmView(interaction.user.id),
            ephemeral=True,
        )


class BauCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._painel_channel_id: int | None = None
        self._painel_message_id: int | None = None
        self._painel_refreshed_on_ready = False

    async def cog_load(self) -> None:
        repo.initialize()
        channel_id, message_id = _load_painel_ref()
        self._painel_channel_id = channel_id
        self._painel_message_id = message_id
        self.bot.add_view(BauPainelView())
        log.info(
            "BauCog carregado (painel_channel=%s, painel_msg=%s).",
            channel_id,
            message_id,
        )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._painel_refreshed_on_ready:
            return
        self._painel_refreshed_on_ready = True
        await self.atualizar_painel()

    async def atualizar_painel(self) -> None:
        if not self._painel_channel_id or not self._painel_message_id:
            return
        channel = self.bot.get_channel(self._painel_channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(self._painel_channel_id)
            except Exception as exc:
                log.error("Nao foi possivel obter canal do painel: %s", exc)
                return
        try:
            message = await channel.fetch_message(self._painel_message_id)
            await message.edit(embed=_build_painel_embed(), view=BauPainelView())
        except discord.NotFound:
            log.warning("Mensagem do painel nao encontrada; recriando...")
            try:
                message = await channel.send(
                    embed=_build_painel_embed(),
                    view=BauPainelView(),
                )
                self._painel_channel_id = message.channel.id
                self._painel_message_id = message.id
                _save_painel_ref(message.channel.id, message.id)
            except Exception:
                log.error("Erro ao recriar painel do bau.", exc_info=True)
        except Exception:
            log.error("Erro ao atualizar painel do bau.", exc_info=True)

    @app_commands.command(
        name="bau_setup",
        description="Posta o painel do Bau da Gerencia no canal configurado.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bau_setup(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if self._painel_channel_id and self._painel_message_id:
            channel = self.bot.get_channel(self._painel_channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(
                        self._painel_channel_id
                    )
                except Exception:
                    channel = None
            if channel:
                try:
                    message = await channel.fetch_message(self._painel_message_id)
                    await message.edit(
                        embed=_build_painel_embed(),
                        view=BauPainelView(),
                    )
                    await interaction.followup.send(
                        "\u26a0\ufe0f O painel do Bau ja esta ativo!",
                        ephemeral=True,
                    )
                    return
                except discord.NotFound:
                    pass

        channel = self.bot.get_channel(CANAL_BAU_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(CANAL_BAU_ID)
            except Exception:
                await interaction.followup.send(
                    "\u274c Canal do bau nao encontrado. Verifique o ID configurado.",
                    ephemeral=True,
                )
                return

        message = await channel.send(
            embed=_build_painel_embed(),
            view=BauPainelView(),
        )
        self._painel_channel_id = message.channel.id
        self._painel_message_id = message.id
        _save_painel_ref(message.channel.id, message.id)
        log.info(
            "Painel do bau criado por %s (msg=%s, channel=%s).",
            interaction.user.id,
            message.id,
            message.channel.id,
        )
        await interaction.followup.send(
            f"\u2705 Painel do Bau postado em {channel.mention}!",
            ephemeral=True,
        )

    @bau_setup.error
    async def _bau_setup_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "\u274c Voce precisa da permissao **Gerenciar Servidor**.",
                ephemeral=True,
            )
            return
        log.error("Erro em /bau_setup: %s", error, exc_info=True)
        try:
            await interaction.response.send_message(
                "\u274c Erro inesperado.",
                ephemeral=True,
            )
        except discord.InteractionResponded:
            await interaction.followup.send(
                "\u274c Erro inesperado.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BauCog(bot))
    log.info("BauCog registrado.")
