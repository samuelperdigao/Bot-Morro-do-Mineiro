"""Regras de negócio e persistência das encomendas (sem dependência do Discord)."""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from core.date_utils import BRAZIL_TZ

STATUS = ("pendente", "em_producao", "pronta", "entregue", "cancelada")
STATUS_ATIVOS = ("pendente", "em_producao", "pronta")
STATUS_FINAIS = ("entregue", "cancelada")
TRANSICOES = {
    "pendente":    {"em_producao", "pronta", "entregue", "cancelada"},
    "em_producao": {"pronta", "entregue", "cancelada"},
    "pronta":      {"entregue", "cancelada"},
}

STATUS_LABEL = {
    "pendente": "Pendente",
    "em_producao": "Em produção",
    "pronta": "Pronta",
    "entregue": "Entregue",
    "cancelada": "Cancelada",
}
STATUS_EMOJI = {
    "pendente": "🟠",
    "em_producao": "🔵",
    "pronta": "🟡",
    "entregue": "✅",
    "cancelada": "❌",
}

QUANTIDADE_MAXIMA = 1_000_000
VALOR_MAXIMO_CENTAVOS = 99_999_999_999  # R$ 999.999.999,99

_RE_INTEIRO = re.compile(r"[0-9]+")
_RE_MILHAR = re.compile(r"[0-9]{1,3}(?:\.[0-9]{3})+")
_RE_PREFIXO_REAL = re.compile(r"^r\$\s*", re.IGNORECASE)


class TransicaoInvalidaError(ValueError):
    """A mudança de status pedida não é permitida a partir do status atual."""


class EncomendaDesatualizadaError(ValueError):
    """Outra pessoa alterou o status entre a leitura e a escrita."""


class EncomendaNaoEncontradaError(LookupError):
    """A encomenda não existe no banco."""


# ── Funções puras ─────────────────────────────────────────────────────────────

def agora_iso() -> str:
    return datetime.now(BRAZIL_TZ).isoformat(timespec="seconds")


def parse_quantidade(texto: str | None) -> int:
    valor = (texto or "").strip()
    if not valor:
        raise ValueError("Informe a quantidade.")
    if not _RE_INTEIRO.fullmatch(valor):
        raise ValueError("A quantidade deve ser um número inteiro maior que zero (ex.: 50).")
    quantidade = int(valor)
    if quantidade <= 0:
        raise ValueError("A quantidade deve ser maior que zero.")
    if quantidade > QUANTIDADE_MAXIMA:
        raise ValueError(f"A quantidade máxima é {QUANTIDADE_MAXIMA:,}.".replace(",", "."))
    return quantidade


def parse_valor_centavos(texto: str | None) -> int:
    """Converte '1500', '1500,50', '1.500', '1.500,00' ou 'R$ 1.500,00' em centavos."""
    valor = _RE_PREFIXO_REAL.sub("", (texto or "").strip()).replace(" ", "")
    if not valor:
        raise ValueError("Informe o valor (ex.: 1.500,00).")

    inteiro, sep, decimal = valor.partition(",")
    if sep and not re.fullmatch(r"[0-9]{1,2}", decimal):
        raise ValueError("Valor inválido. Use até 2 casas decimais após a vírgula (ex.: 1.500,00).")
    if _RE_INTEIRO.fullmatch(inteiro):
        reais = int(inteiro)
    elif _RE_MILHAR.fullmatch(inteiro):
        reais = int(inteiro.replace(".", ""))
    else:
        raise ValueError("Valor inválido. Use o formato 1.500,00 (ponto para milhar, vírgula para centavos).")

    centavos = reais * 100 + (int(decimal.ljust(2, "0")) if sep else 0)
    if centavos <= 0:
        raise ValueError("O valor deve ser maior que zero.")
    if centavos > VALOR_MAXIMO_CENTAVOS:
        raise ValueError("Valor muito alto. Confira o número digitado.")
    return centavos


def format_brl(centavos: int) -> str:
    reais, cents = divmod(int(centavos), 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{cents:02d}"


def formatar_numero(n: int) -> str:
    return f"#{int(n):03d}"


def status_com_emoji(status: str) -> str:
    return f"{STATUS_EMOJI.get(status, '')} {STATUS_LABEL.get(status, status)}".strip()


def transicao_permitida(atual: str, novo: str) -> bool:
    return novo in TRANSICOES.get(atual, set())


# ── Repositório ───────────────────────────────────────────────────────────────

class EncomendaRepository:
    """Acesso às tabelas encomendas/encomenda_eventos sobre uma conexão SQLite."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        self.conn = conn

    @contextmanager
    def _transacao(self):
        if self.conn.in_transaction:
            # Conexão compartilhada do bot: escrita pendente de outro módulo
            # seria confirmada no próximo commit de qualquer forma.
            self.conn.commit()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.rollback()
            raise
        self.conn.commit()

    def _evento(
        self,
        encomenda_id: int,
        tipo: str,
        user_id: str | None,
        *,
        de_status: str | None = None,
        para_status: str | None = None,
        detalhe: str | None = None,
        criado_em: str | None = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO encomenda_eventos
               (encomenda_id, tipo, de_status, para_status, user_id, detalhe, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (encomenda_id, tipo, de_status, para_status, user_id, detalhe, criado_em or agora_iso()),
        )

    def criar(
        self,
        guild_id: str,
        familia: str,
        quantidade: int,
        valor_centavos: int,
        data: str,
        observacao: str | None,
        solicitante_id: str,
    ) -> sqlite3.Row:
        familia = (familia or "").strip()
        if not familia:
            raise ValueError("Informe a família.")
        if int(quantidade) <= 0 or int(valor_centavos) <= 0:
            raise ValueError("Quantidade e valor precisam ser maiores que zero.")
        observacao = (observacao or "").strip() or None
        agora = agora_iso()

        with self._transacao() as conn:
            numero = conn.execute(
                "SELECT COALESCE(MAX(numero), 0) + 1 FROM encomendas WHERE guild_id=?",
                (str(guild_id),),
            ).fetchone()[0]
            cursor = conn.execute(
                """INSERT INTO encomendas
                   (guild_id, numero, familia, quantidade, valor_centavos, data,
                    observacao, status, solicitante_id, criado_em, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pendente', ?, ?, ?)""",
                (
                    str(guild_id), numero, familia, int(quantidade), int(valor_centavos),
                    data, observacao, str(solicitante_id), agora, agora,
                ),
            )
            encomenda_id = cursor.lastrowid
            self._evento(
                encomenda_id, "criada", str(solicitante_id),
                para_status="pendente", criado_em=agora,
            )
        return self.obter(encomenda_id)

    def obter(self, encomenda_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM encomendas WHERE id=?", (int(encomenda_id),),
        ).fetchone()

    def obter_por_mensagem_pedidos(self, message_id: int | str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM encomendas WHERE pedidos_message_id=?", (str(message_id),),
        ).fetchone()

    def eventos(self, encomenda_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM encomenda_eventos WHERE encomenda_id=? ORDER BY id",
            (int(encomenda_id),),
        ).fetchall()

    def salvar_mensagem_pedidos(self, encomenda_id: int, channel_id: int | str, message_id: int | str) -> None:
        with self._transacao() as conn:
            conn.execute(
                "UPDATE encomendas SET pedidos_channel_id=?, pedidos_message_id=? WHERE id=?",
                (str(channel_id), str(message_id), int(encomenda_id)),
            )

    def salvar_mensagem_arquivo(self, encomenda_id: int, channel_id: int | str, message_id: int | str) -> None:
        with self._transacao() as conn:
            conn.execute(
                "UPDATE encomendas SET arquivo_channel_id=?, arquivo_message_id=? WHERE id=?",
                (str(channel_id), str(message_id), int(encomenda_id)),
            )

    def registrar_erro(self, encomenda_id: int, user_id: str | None, detalhe: str) -> None:
        with self._transacao():
            self._evento(int(encomenda_id), "erro", user_id, detalhe=detalhe[:500])

    def transitar(
        self,
        encomenda_id: int,
        novo_status: str,
        user_id: str,
        *,
        status_esperado: str | None = None,
    ) -> sqlite3.Row:
        """Muda o status de forma atômica (compare-and-set sobre o status atual).

        `status_esperado` é o status que o chamador leu antes (ex.: ao abrir a
        confirmação). Se o banco já estiver diferente, ninguém sobrescreve a
        mudança de outra pessoa: levanta EncomendaDesatualizadaError.
        """
        if novo_status not in STATUS:
            raise TransicaoInvalidaError(f"Status desconhecido: {novo_status}")
        agora = agora_iso()

        with self._transacao() as conn:
            row = conn.execute(
                "SELECT status FROM encomendas WHERE id=?", (int(encomenda_id),),
            ).fetchone()
            if row is None:
                raise EncomendaNaoEncontradaError(f"Encomenda {encomenda_id} não encontrada.")
            atual = row["status"]
            if status_esperado is not None and atual != status_esperado:
                raise EncomendaDesatualizadaError(
                    f"Status mudou de {status_esperado} para {atual}."
                )
            if not transicao_permitida(atual, novo_status):
                raise TransicaoInvalidaError(
                    f"Não é possível mudar de {STATUS_LABEL.get(atual, atual)} "
                    f"para {STATUS_LABEL.get(novo_status, novo_status)}."
                )
            finalizado_em = agora if novo_status in STATUS_FINAIS else None
            cursor = conn.execute(
                """UPDATE encomendas
                   SET status=?,
                       responsavel_id=COALESCE(responsavel_id, ?),
                       atualizado_em=?,
                       finalizado_em=COALESCE(?, finalizado_em)
                   WHERE id=? AND status=?""",
                (novo_status, str(user_id), agora, finalizado_em, int(encomenda_id), atual),
            )
            if cursor.rowcount != 1:
                raise EncomendaDesatualizadaError("Outra pessoa já atualizou esta encomenda.")
            self._evento(
                int(encomenda_id), "status", str(user_id),
                de_status=atual, para_status=novo_status, criado_em=agora,
            )
        return self.obter(encomenda_id)

    def listar_ativas(self, guild_id: str) -> list[sqlite3.Row]:
        marcadores = ",".join("?" for _ in STATUS_ATIVOS)
        return self.conn.execute(
            f"""SELECT * FROM encomendas
                WHERE guild_id=? AND status IN ({marcadores})
                ORDER BY numero""",
            (str(guild_id), *STATUS_ATIVOS),
        ).fetchall()

    def excluir(self, encomenda_id: int) -> None:
        """Desfaz a criação quando o pedido não pôde ser postado em #pedidos."""
        with self._transacao() as conn:
            conn.execute("DELETE FROM encomenda_eventos WHERE encomenda_id=?", (int(encomenda_id),))
            conn.execute("DELETE FROM encomendas WHERE id=?", (int(encomenda_id),))
