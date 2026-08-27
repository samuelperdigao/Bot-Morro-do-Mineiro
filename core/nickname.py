"""
core/nickname.py - Montagem dos apelidos com a tag do cargo.

Modulo puro (sem I/O): recebe membros/strings e devolve strings, para poder
ser testado sem Discord.
"""

from __future__ import annotations

import re

from core.role_sync import normalize_role_name

TAG_LIDER   = "[LIDER]"
TAG_VICE    = "[VICE]"
TAG_GERENTE = "[GRT]"
TAG_MEMBRO  = "[MBR]"

NICK_MAX = 32  # limite do Discord

# Ordem = prioridade (o cargo mais alto vence).
TAG_RULES = (
    (TAG_LIDER,   ("| 01 Dono",)),
    (TAG_VICE,    ("| 02",)),
    (TAG_GERENTE, ("| Gerente Geral",)),   # + regra por prefixo em _is_gerente
    (TAG_MEMBRO,  ("| Membro",)),
)
# "| 03", "| Flanelinha" e "| Pedir Set" ficam de fora de proposito: sem tag.

_TAG_PREFIX_RE = re.compile(r"^\s*\[[^\]]{1,12}\]\s*")

_SUFIXO_ID = " | "


def _is_gerente(normalized_name: str) -> bool:
    """Qualquer '| Gerente de ...' entra em [GRT] sem precisar listar um a um."""
    return normalized_name.startswith("gerente")


def _role_ids(member) -> set[int]:
    ids = set()
    for role in getattr(member, "roles", ()) or ():
        role_id = getattr(role, "id", None)
        if isinstance(role_id, int):
            ids.add(role_id)
    return ids


def _role_names(member) -> set[str]:
    return {
        normalize_role_name(getattr(role, "name", "") or "")
        for role in getattr(member, "roles", ()) or ()
    }


def tag_for_member(member, *, member_role_id: int | str | None = None) -> str | None:
    """Devolve a tag de maior prioridade entre os cargos do membro."""

    names = _role_names(member)
    ids   = _role_ids(member)

    try:
        configured_member_role = int(member_role_id) if member_role_id else None
    except (TypeError, ValueError):
        configured_member_role = None

    for tag, role_names in TAG_RULES:
        expected = {normalize_role_name(name) for name in role_names}
        if names & expected:
            return tag
        if tag == TAG_GERENTE and any(_is_gerente(name) for name in names):
            return tag
        if tag == TAG_MEMBRO and configured_member_role is not None and configured_member_role in ids:
            return tag
    return None


def strip_tag(nick: str | None) -> str:
    """Remove a tag do inicio do apelido. Idempotente."""

    texto = (nick or "").strip()
    while True:
        novo = _TAG_PREFIX_RE.sub("", texto, count=1)
        if novo == texto:
            return texto.strip()
        texto = novo.strip()


def _truncar_base(base: str, disponivel: int) -> str:
    """Corta o nome preservando o sufixo ' | ID' quando ele existe."""

    nome, sep, sufixo = base.rpartition(_SUFIXO_ID)
    if not sep:
        return base[:disponivel].strip()

    sufixo_completo = f"{_SUFIXO_ID}{sufixo}"
    espaco_nome = disponivel - len(sufixo_completo)
    if espaco_nome <= 0:
        return base[:disponivel].strip()
    return f"{nome[:espaco_nome].strip()}{sufixo_completo}"


def build_nick(base: str, tag: str | None) -> str:
    """Monta '<tag> <base>' respeitando o limite de 32 caracteres."""

    base = (base or "").strip()
    if not tag:
        return base[:NICK_MAX].strip()

    prefixo = f"{tag} "
    disponivel = NICK_MAX - len(prefixo)
    if disponivel <= 0:
        return base[:NICK_MAX].strip()
    if len(base) <= disponivel:
        return f"{prefixo}{base}"
    return f"{prefixo}{_truncar_base(base, disponivel)}"


def build_nick_from_parts(nome: str, id_jogo: str | None, tag: str | None) -> str:
    """Monta o apelido a partir do nome e do ID informados no modal do Set."""

    nome = (nome or "").strip()
    id_jogo = str(id_jogo or "").strip()
    base = f"{nome}{_SUFIXO_ID}{id_jogo}" if id_jogo else nome
    return build_nick(base, tag)


def desired_nick(member, tag: str | None) -> str | None:
    """Apelido esperado para o membro, ou None quando nao ha tag aplicavel."""

    if not tag:
        return None
    atual = getattr(member, "nick", None) or getattr(member, "display_name", "") or ""
    return build_nick(strip_tag(atual), tag)
