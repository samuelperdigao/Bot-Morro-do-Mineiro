"""Helpers para Components V2 do Discord com discord.py 2.3.2.

A lib ainda nao tem classes para Components V2, entao as mensagens sao montadas
como dicts (payload cru) e enviadas pela camada HTTP do proprio discord.py.

Regras do V2 que importam aqui:
- a mensagem precisa da flag IS_COMPONENTS_V2 e nao pode ter content/embeds;
- limite de 40 componentes por mensagem (contando os aninhados);
- botoes ficam dentro de Action Row ou como accessory de Section.
"""

from __future__ import annotations

import json
from typing import Any

import discord
from discord.http import Route

FLAG_EPHEMERAL = 1 << 6
FLAG_COMPONENTS_V2 = 1 << 15
LIMITE_COMPONENTES = 40

# Tipos de componente
ACTION_ROW = 1
BUTTON = 2
SECTION = 9
TEXT_DISPLAY = 10
THUMBNAIL = 11
MEDIA_GALLERY = 12
SEPARATOR = 14
CONTAINER = 17

# Estilos de botao
PRIMARY = 1
SECONDARY = 2
SUCCESS = 3
DANGER = 4

# Tipos de resposta de interacao
RESPOSTA_MENSAGEM = 4
RESPOSTA_ATUALIZAR = 7

SEM_MENCOES = {"parse": []}


# ── Construtores ──────────────────────────────────────────────────────────────

def texto(conteudo: str) -> dict[str, Any]:
    return {"type": TEXT_DISPLAY, "content": conteudo}


def separador(divisor: bool = True, espacamento: int = 1) -> dict[str, Any]:
    return {"type": SEPARATOR, "divider": divisor, "spacing": espacamento}


def botao(
    label: str,
    custom_id: str,
    estilo: int = SECONDARY,
    desabilitado: bool = False,
) -> dict[str, Any]:
    return {
        "type": BUTTON,
        "style": estilo,
        "label": label,
        "custom_id": custom_id,
        "disabled": desabilitado,
    }


def linha(botoes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": ACTION_ROW, "components": botoes}


def secao(textos: list[str], thumbnail_url: str) -> dict[str, Any]:
    return {
        "type": SECTION,
        "components": [texto(t) for t in textos],
        "accessory": {"type": THUMBNAIL, "media": {"url": thumbnail_url}},
    }


def galeria(urls: list[str]) -> dict[str, Any]:
    return {"type": MEDIA_GALLERY, "items": [{"media": {"url": u}} for u in urls]}


def container(filhos: list[dict[str, Any]], cor: int | None = None) -> dict[str, Any]:
    dados: dict[str, Any] = {"type": CONTAINER, "components": filhos}
    if cor is not None:
        dados["accent_color"] = cor
    return dados


def contar_componentes(componentes: list[dict[str, Any]]) -> int:
    """Conta componentes de forma recursiva (limite do Discord: 40 por mensagem)."""
    total = 0
    for comp in componentes:
        total += 1
        total += contar_componentes(comp.get("components", []))
        if "accessory" in comp:
            total += 1
    return total


# ── Envio ─────────────────────────────────────────────────────────────────────

def _corpo(componentes: list[dict[str, Any]], efemero: bool = False) -> dict[str, Any]:
    flags = FLAG_COMPONENTS_V2 | (FLAG_EPHEMERAL if efemero else 0)
    return {
        "flags": flags,
        "components": componentes,
        "allowed_mentions": SEM_MENCOES,
    }


async def responder(
    interaction: discord.Interaction,
    componentes: list[dict[str, Any]],
    *,
    atualizar: bool = False,
) -> None:
    """Responde a uma interacao com uma mensagem V2.

    atualizar=False cria uma mensagem nova efemera (tipo 4);
    atualizar=True edita a mensagem do componente clicado (tipo 7).
    """
    if atualizar:
        corpo: dict[str, Any] = {"components": componentes}
        tipo = RESPOSTA_ATUALIZAR
    else:
        corpo = _corpo(componentes, efemero=True)
        tipo = RESPOSTA_MENSAGEM
    rota = Route(
        "POST",
        "/interactions/{interaction_id}/{interaction_token}/callback",
        interaction_id=interaction.id,
        interaction_token=interaction.token,
    )
    await interaction._state.http.request(rota, json={"type": tipo, "data": corpo})


async def editar_original(
    interaction: discord.Interaction, componentes: list[dict[str, Any]]
) -> None:
    """Edita a resposta original da interacao (valida por 15 minutos)."""
    rota = Route(
        "PATCH",
        "/webhooks/{webhook_id}/{webhook_token}/messages/@original",
        webhook_id=interaction.application_id,
        webhook_token=interaction.token,
    )
    await interaction._state.http.request(rota, json={"components": componentes})


async def enviar_canal(
    http,
    canal_id: int,
    componentes: list[dict[str, Any]],
    arquivos: list[discord.File] | None = None,
) -> dict[str, Any]:
    """Posta uma mensagem V2 num canal. Retorna o JSON da mensagem criada."""
    rota = Route("POST", "/channels/{channel_id}/messages", channel_id=canal_id)
    corpo = _corpo(componentes)
    if not arquivos:
        return await http.request(rota, json=corpo)

    corpo["attachments"] = [
        {"id": i, "filename": arq.filename} for i, arq in enumerate(arquivos)
    ]
    form: list[dict[str, Any]] = [{"name": "payload_json", "value": json.dumps(corpo)}]
    for i, arq in enumerate(arquivos):
        arq.reset()
        form.append(
            {
                "name": f"files[{i}]",
                "value": arq.fp,
                "filename": arq.filename,
                "content_type": "application/octet-stream",
            }
        )
    return await http.request(rota, form=form, files=arquivos)


async def editar_mensagem(
    http, canal_id: int, mensagem_id: int, componentes: list[dict[str, Any]]
) -> None:
    """Edita uma mensagem V2 ja postada (mantem os anexos existentes)."""
    rota = Route(
        "PATCH",
        "/channels/{channel_id}/messages/{message_id}",
        channel_id=canal_id,
        message_id=mensagem_id,
    )
    await http.request(
        rota, json={"components": componentes, "allowed_mentions": SEM_MENCOES}
    )
