"""Painel rapido e inteligente do Bau da Gerencia."""

from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import dataclass, field
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
    TOTAL_PRODUTOS,
    UndoOperation,
    UndoResult,
    agora_str,
)
from core.logger import get_logger


log = get_logger("bau", "bau.log")

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "bau.db"
PAINEL_JSON = BASE_DIR / "bau_painel.json"

CANAL_BAU_ID = 1474869322387292357
CANAL_LOG_ID = 1499589255784173678

CATEGORY_PAGE_SIZE = 5
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


def _build_painel_embed() -> discord.Embed:
    stock = repo.get_stock()
    embed = discord.Embed(
        title="\U0001f3e6 Bau da Gerencia",
        description=(
            "Selecione uma categoria para adicionar ou retirar varios produtos "
            "de uma vez."
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
            "Selecione uma categoria para iniciar a atualizacao."
        )
    embed.set_footer(text=f"Ultima atualizacao: {agora_str()} (Brasilia)")
    return embed


def _chunk_lines(lines: tuple[MovementLine, ...], size: int = 20):
    for index in range(0, len(lines), size):
        yield lines[index:index + size]


def _build_operation_log_embeds(
    result: OperationResult,
    user: discord.abc.User,
) -> list[discord.Embed]:
    embeds: list[discord.Embed] = []
    for line in result.lines:
        is_entry = result.tipo == "entrada"
        title_prefix = "\U0001f7e2 Entrada" if is_entry else "\U0001f534 Sa\u00edda"
        quantity_prefix = "+" if is_entry else "-"
        embed = discord.Embed(
            title=f"{title_prefix} \u2014 {line.produto}",
            color=discord.Color.green() if is_entry else discord.Color.red(),
        )
        embed.add_field(
            name="\U0001f464 Usu\u00e1rio",
            value=f"{user.display_name}\n(`{user.id}`)",
            inline=True,
        )
        embed.add_field(
            name="\U0001f4e6 Quantidade",
            value=f"{quantity_prefix}{_format_number(line.quantidade)}",
            inline=True,
        )
        embed.add_field(
            name="\U0001f5c3\ufe0f Estoque ap\u00f3s",
            value=f"{_format_number(line.estoque_depois)} unidades",
            inline=True,
        )
        embed.add_field(
            name="\U0001f550 Hor\u00e1rio",
            value=result.criado_em,
            inline=False,
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


def _is_bau_admin(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(getattr(permissions, "administrator", False))


def _parse_category_quantity(raw: str) -> int:
    value = raw.strip()
    if not value:
        return 0
    if not re.fullmatch(r"[\d\s.,]+", value):
        raise ValueError("Use somente numeros inteiros positivos.")
    digits = re.sub(r"[\s.,]", "", value)
    if not digits.isdigit():
        raise ValueError("Use somente numeros inteiros positivos.")
    return int(digits)


@dataclass
class CategorySession:
    category: str
    movement_type: str
    requester_id: int
    products: tuple[str, ...]
    quantities: dict[str, int] = field(default_factory=dict)
    page: int = 0
    operation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    generation: int = field(default_factory=repo.get_generation)

    @property
    def page_count(self) -> int:
        return max(1, math.ceil(len(self.products) / CATEGORY_PAGE_SIZE))

    def page_products(self, page: int | None = None) -> tuple[str, ...]:
        selected_page = self.page if page is None else page
        start = selected_page * CATEGORY_PAGE_SIZE
        return self.products[start:start + CATEGORY_PAGE_SIZE]

    def items(self) -> list[tuple[str, int]]:
        return [
            (product, self.quantities[product])
            for product in self.products
            if self.quantities.get(product, 0) > 0
        ]


def _build_category_page_embed(session: CategorySession) -> discord.Embed:
    stock = repo.get_stock()
    lines = []
    for product in session.page_products():
        quantity = session.quantities.get(product, 0)
        informed = (
            f"**{_format_number(quantity)}**"
            if quantity > 0
            else "*nao informado*"
        )
        lines.append(
            f"\u2022 **{product}**: {informed} "
            f"(estoque: {_format_number(stock.get(product, 0))})"
        )
    embed = discord.Embed(
        title=f"{_movement_label(session.movement_type)} - {session.category}",
        description="\n".join(lines),
        color=(
            discord.Color.green()
            if session.movement_type == "entrada"
            else discord.Color.red()
        ),
    )
    embed.set_footer(
        text=(
            f"Pagina {session.page + 1}/{session.page_count} | "
            f"{len(session.items())} produto(s) preenchido(s)"
        )
    )
    return embed


class CategoryQuantityModal(discord.ui.Modal):
    def __init__(
        self,
        session: CategorySession,
        page: int | None = None,
        forward: bool = True,
    ) -> None:
        self.page = session.page if page is None else page
        self.forward = forward
        super().__init__(
            title=(
                f"{_movement_label(session.movement_type)} "
                f"{self.page + 1}/{session.page_count}"
            )[:45]
        )
        self.session = session
        self.inputs: list[tuple[str, discord.ui.TextInput]] = []
        stock = repo.get_stock()
        for product in session.page_products(self.page):
            current = session.quantities.get(product, 0)
            text_input = discord.ui.TextInput(
                label=product[:45],
                placeholder=(
                    f"Estoque atual: {_format_number(stock.get(product, 0))}"
                ),
                default=str(current) if current > 0 else None,
                required=False,
                max_length=12,
            )
            self.inputs.append((product, text_input))
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        parsed: dict[str, int] = {}
        errors: list[str] = []
        for product, text_input in self.inputs:
            try:
                parsed[product] = _parse_category_quantity(
                    str(text_input.value)
                )
            except ValueError:
                errors.append(product)

        if errors:
            await interaction.response.edit_message(
                content=(
                    "\u274c Quantidade invalida em: "
                    + ", ".join(f"**{product}**" for product in errors)
                    + ". Use apenas numeros inteiros positivos."
                ),
                embed=_build_category_page_embed(self.session),
                view=CategoryPageView(self.session),
            )
            return

        for product, quantity in parsed.items():
            if quantity > 0:
                self.session.quantities[product] = quantity
            else:
                self.session.quantities.pop(product, None)
        self.session.page = self.page

        if self.forward and self.page < self.session.page_count - 1:
            await interaction.response.send_modal(
                CategoryQuantityModal(self.session, self.page + 1, forward=True)
            )
        else:
            await interaction.response.edit_message(
                content="\u2705 Pagina salva.",
                embed=_build_category_page_embed(self.session),
                view=CategoryPageView(self.session),
            )


class CategoryMovementView(RequesterView):
    def __init__(self, category: str, requester_id: int) -> None:
        super().__init__(requester_id, timeout=300)
        self.category = category

    async def _start(
        self,
        interaction: discord.Interaction,
        movement_type: str,
    ) -> None:
        session = CategorySession(
            self.category,
            movement_type,
            interaction.user.id,
            tuple(CATEGORIAS[self.category]),
        )
        await interaction.response.send_modal(CategoryQuantityModal(session))

    @discord.ui.button(
        label="Entrada",
        emoji="\u2705",
        style=discord.ButtonStyle.success,
    )
    async def entry(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._start(interaction, "entrada")

    @discord.ui.button(
        label="Retirada",
        emoji="\u274c",
        style=discord.ButtonStyle.danger,
    )
    async def exit(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._start(interaction, "saida")

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="Lancamento cancelado.",
            embed=None,
            view=None,
        )
        self.stop()


class CategoryPageView(RequesterView):
    def __init__(self, session: CategorySession) -> None:
        super().__init__(session.requester_id, timeout=600)
        self.session = session
        self.previous.disabled = session.page == 0
        self.next.disabled = session.page >= session.page_count - 1

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.secondary)
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            CategoryQuantityModal(self.session, self.session.page - 1, forward=False)
        )

    @discord.ui.button(label="Editar pagina", style=discord.ButtonStyle.primary)
    async def edit_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            CategoryQuantityModal(self.session, forward=False)
        )

    @discord.ui.button(label="Proxima", style=discord.ButtonStyle.secondary)
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            CategoryQuantityModal(self.session, self.session.page + 1, forward=False)
        )

    @discord.ui.button(label="Enviar", style=discord.ButtonStyle.success)
    async def send(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self.session.items():
            await interaction.response.send_message(
                "\u274c Informe ao menos uma quantidade antes de enviar.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            content="Processando lancamento...",
            embed=None,
            view=None,
        )
        try:
            result = repo.apply_category_operation(
                self.session.movement_type,
                self.session.items(),
                str(interaction.user.id),
                interaction.user.display_name,
                self.session.operation_id,
                self.session.generation,
            )
        except DuplicateOperationError:
            await interaction.edit_original_response(
                content="\u26a0\ufe0f Este lancamento ja foi processado.",
                embed=None,
                view=None,
            )
            return
        except StaleOperationError:
            await interaction.edit_original_response(
                content=(
                    "\u26a0\ufe0f O bau foi zerado depois que este lancamento "
                    "foi iniciado. Comece novamente."
                ),
                embed=None,
                view=None,
            )
            return
        except Exception:
            log.error("Erro ao processar categoria do bau.", exc_info=True)
            await interaction.edit_original_response(
                content="\u274c Erro ao registrar o lancamento.",
                embed=None,
                view=None,
            )
            return

        operation = result.operation
        if operation.lines:
            await _refresh_panel(interaction.client)
            await _send_log(
                interaction.client,
                _build_operation_log_embeds(operation, interaction.user),
            )

        description = (
            f"\u2705 **{len(operation.lines)}** produto(s) registrado(s)."
            if operation.lines
            else "\u26a0\ufe0f Nenhum produto foi registrado."
        )
        if result.skipped:
            skipped_lines = "\n".join(
                f"\u2022 **{product}**: solicitado "
                f"{_format_number(quantity)}, disponivel "
                f"{_format_number(available)}"
                for product, quantity, available in result.skipped
            )
            description += (
                "\n\n**Ignorados por falta de estoque:**\n" + skipped_lines
            )
        await interaction.edit_original_response(
            content=None,
            embed=discord.Embed(
                title="Resultado do lancamento",
                description=description,
                color=(
                    discord.Color.green()
                    if operation.lines
                    else discord.Color.gold()
                ),
            ),
            view=None,
        )
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger)
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="Lancamento cancelado. Nenhum item foi alterado.",
            embed=None,
            view=None,
        )
        self.stop()


class CategorySelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label=category, value=category)
            for category in CATEGORIAS
        ]
        super().__init__(
            custom_id="bau:categoria_select",
            placeholder="Selecione uma categoria...",
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        category = self.values[0]
        await interaction.response.send_message(
            f"\U0001f4e6 **{category}** - escolha a operacao:",
            view=CategoryMovementView(category, interaction.user.id),
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

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if _is_bau_admin(interaction):
            return True
        await interaction.response.send_message(
            "\u274c Apenas administradores podem zerar o bau.",
            ephemeral=True,
        )
        return False

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
        label="Desfazer",
        emoji="\u21a9\ufe0f",
        style=discord.ButtonStyle.secondary,
        custom_id="bau:desfazer",
        row=1,
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
        label="Zerar",
        emoji="\u26a0\ufe0f",
        style=discord.ButtonStyle.danger,
        custom_id="bau:limpar",
        row=1,
    )
    async def clear(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not _is_bau_admin(interaction):
            await interaction.response.send_message(
                "\u274c Apenas administradores podem zerar o bau.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="\u26a0\ufe0f Zerar todo o Bau?",
            description=(
                "Esta acao vai:\n"
                f"\u2022 definir **todos os {TOTAL_PRODUTOS} produtos como zero**;\n"
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
