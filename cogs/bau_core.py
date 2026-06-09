"""Regras de negocio e persistencia do Bau da Gerencia."""

from __future__ import annotations

import difflib
import re
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TZ_SP = ZoneInfo("America/Sao_Paulo")

CATEGORIAS = {
    "\U0001f392 Itens Gerais": [
        "Drogas", "Camisa de Forca", "Placa Clonada", "Ticket Corrida",
        "Bloqueador de Sinal", "Masterpick", "Adrenalina", "C4",
        "Capuz", "Colete", "Algema", "Nitro", "Chimas", "Vaselina",
        "Pager", "Tesoura",
    ],
    "\U0001f9f1 Materiais": [
        "Alum\u00ednio", "Cobre", "Borracha", "Pl\u00e1stico", "Ferro", "Tecido",
    ],
    "\U0001f52b Municoes": ["5mm", "9mm", "762mm", "12cbc"],
    "\U0001f527 Attachs": [
        "Clip Extendido", "Supressor", "Compensador",
        "Lanterna Acoplavel", "Mira Avancada", "Grip Avancado",
    ],
    "\U0001f48a Drogas/Efeitos": [
        "Balinha", "Viagra", "Erva", "Oxy", "Lanca Perfume",
        "Meta", "Farinha", "Rape", "Ayahuasca", "Skunk", "Heroina",
    ],
    "\U0001f52a Armas Brancas": [
        "Katana", "Pao (Arma Branca)", "Canivete", "Picareta",
        "Placa (Arma Branca)", "Tablet Corrida",
    ],
    "\U0001f9f0 Kit de Desmanche": ["Kit de Desmanche"],
    "\U0001f52b Armas 1": [
        "Pistola Colt .45", "Pistola M1911", "Sub Skorpion VZ61",
        "Sub Uzi", "Sub M-Tar 21", "Fuzil AK-103",
        "Fuzil G36C", "Escopeta Remington (Armas 1)",
    ],
    "\U0001f52b Armas 2": [
        "Pistola Five-Seven", "Pistola D-Eagle", "Sub Thompson",
        "Sub Tec-9", "Sub M-Tar X", "Fuzil AK-47",
        "Fuzil AUG", "Escopeta Remington (Armas 2)",
    ],
    "\U0001f697 Flipper/Chaves": [
        "Flipper MK5", "Flipper MK4", "Flipper MK3", "Flipper MK2",
        "Flipper MK1", "Chave Platina", "Chave Gold",
    ],
    "\U0001f5dd\ufe0f Chaves de Acao": ["MK1", "MK2", "MK3", "MK4", "MK5"],
    "\U0001f31f Outros": ["FN Fal", "Arco", "Flecha", "M16"],
    "\U0001f4b0 Dinheiro": ["Dinheiro", "Dinheiro Sujo"],
}

TOTAL_PRODUTOS = sum(len(produtos) for produtos in CATEGORIAS.values())

PRODUTO_CATEGORIA = {
    produto: categoria
    for categoria, produtos in CATEGORIAS.items()
    for produto in produtos
}


def agora_str() -> str:
    return datetime.now(TZ_SP).strftime("%d/%m/%Y %H:%M:%S")


def normalize_product_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold()
    return re.sub(r"\s+", " ", value).strip()


NORMALIZED_PRODUCTS = {
    normalize_product_name(produto): produto for produto in PRODUTO_CATEGORIA
}


@dataclass(frozen=True)
class ParseIssue:
    line_number: int
    raw_line: str
    message: str
    suggestions: tuple[str, ...] = ()


@dataclass
class BatchParseResult:
    items: list[tuple[str, int]] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return bool(self.items) and not self.issues


@dataclass(frozen=True)
class MovementLine:
    produto: str
    categoria: str
    quantidade: int
    estoque_antes: int
    estoque_depois: int


@dataclass(frozen=True)
class OperationResult:
    operation_id: str
    tipo: str
    origem: str
    user_id: str
    user_nome: str
    criado_em: str
    lines: tuple[MovementLine, ...]


@dataclass(frozen=True)
class UndoOperation:
    operation_id: str
    tipo: str
    origem: str
    criado_em: str
    items: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class UndoResult:
    operation_id: str
    reverted: tuple[MovementLine, ...]
    skipped: tuple[tuple[str, int, int], ...]


class StockInsufficientError(ValueError):
    def __init__(self, shortages: dict[str, tuple[int, int]]) -> None:
        super().__init__("Estoque insuficiente")
        self.shortages = shortages


class DuplicateOperationError(ValueError):
    pass


class StaleOperationError(ValueError):
    pass


def parse_batch_text(text: str) -> BatchParseResult:
    aggregated: dict[str, int] = {}
    issues: list[ParseIssue] = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            issues.append(ParseIssue(
                line_number,
                raw_line,
                "Use o formato Produto: quantidade.",
            ))
            continue

        raw_product, raw_quantity = line.rsplit(":", 1)
        normalized = normalize_product_name(raw_product)
        product = NORMALIZED_PRODUCTS.get(normalized)
        if product is None:
            matches = difflib.get_close_matches(
                normalized,
                NORMALIZED_PRODUCTS.keys(),
                n=3,
                cutoff=0.52,
            )
            issues.append(ParseIssue(
                line_number,
                raw_line,
                "Produto nao reconhecido.",
                tuple(NORMALIZED_PRODUCTS[match] for match in matches),
            ))
            continue

        quantity_text = raw_quantity.strip()
        if not quantity_text or not re.fullmatch(r"[\d\s.,]+", quantity_text):
            issues.append(ParseIssue(
                line_number,
                raw_line,
                "A quantidade deve ser um numero inteiro positivo.",
            ))
            continue
        digits = re.sub(r"[\s.,]", "", quantity_text)
        if not digits.isdigit() or int(digits) <= 0:
            issues.append(ParseIssue(
                line_number,
                raw_line,
                "A quantidade deve ser maior que zero.",
            ))
            continue

        aggregated[product] = aggregated.get(product, 0) + int(digits)

    if not aggregated and not issues:
        issues.append(ParseIssue(0, "", "Informe pelo menos um produto."))

    ordered_items = [
        (product, aggregated[product])
        for product in PRODUTO_CATEGORIA
        if product in aggregated
    ]
    return BatchParseResult(items=ordered_items, issues=issues)


class BauRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=15000")
            return conn
        except Exception:
            conn.close()
            raise

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS bau_estoque (
                    produto    TEXT PRIMARY KEY,
                    categoria  TEXT NOT NULL,
                    quantidade INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS bau_historico (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    produto    TEXT NOT NULL,
                    categoria  TEXT NOT NULL,
                    tipo       TEXT NOT NULL,
                    quantidade INTEGER NOT NULL,
                    user_id    TEXT NOT NULL,
                    user_nome  TEXT NOT NULL,
                    criado_em  TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bau_operacoes (
                    operation_id TEXT PRIMARY KEY,
                    tipo         TEXT NOT NULL,
                    origem       TEXT NOT NULL,
                    user_id      TEXT NOT NULL,
                    user_nome    TEXT NOT NULL,
                    criado_em    TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bau_meta (
                    chave TEXT PRIMARY KEY,
                    valor TEXT NOT NULL
                );
            """)
            conn.execute(
                "INSERT OR IGNORE INTO bau_meta (chave, valor) "
                "VALUES ('generation', '0')"
            )
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(bau_historico)")
            }
            migrations = {
                "operation_id": "TEXT",
                "origem": "TEXT NOT NULL DEFAULT 'individual'",
                "revertido": "INTEGER NOT NULL DEFAULT 0",
                "revertido_em": "TEXT",
                "revertido_por": "TEXT",
            }
            for column, definition in migrations.items():
                if column not in columns:
                    conn.execute(
                        f"ALTER TABLE bau_historico ADD COLUMN {column} {definition}"
                    )

            conn.execute(
                "UPDATE bau_historico "
                "SET operation_id='legacy-' || id "
                "WHERE operation_id IS NULL OR operation_id=''"
            )
            conn.execute(
                "UPDATE bau_historico SET origem='individual' "
                "WHERE origem IS NULL OR origem=''"
            )
            conn.executescript("""
                CREATE INDEX IF NOT EXISTS idx_bau_historico_operation
                    ON bau_historico(operation_id);
                CREATE INDEX IF NOT EXISTS idx_bau_historico_user
                    ON bau_historico(user_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_bau_historico_product
                    ON bau_historico(produto, id DESC);
            """)

            for categoria, produtos in CATEGORIAS.items():
                for produto in produtos:
                    conn.execute(
                        "INSERT OR IGNORE INTO bau_estoque "
                        "(produto, categoria, quantidade) VALUES (?, ?, 0)",
                        (produto, categoria),
                    )
                    conn.execute(
                        "UPDATE bau_estoque SET categoria=? WHERE produto=?",
                        (categoria, produto),
                    )

    def get_stock(self) -> dict[str, int]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT produto, quantidade FROM bau_estoque"
            ).fetchall()
        return {row["produto"]: int(row["quantidade"]) for row in rows}

    def get_quantity(self, product: str) -> int:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT quantidade FROM bau_estoque WHERE produto=?",
                (product,),
            ).fetchone()
        return int(row["quantidade"]) if row else 0

    def get_generation(self) -> int:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT valor FROM bau_meta WHERE chave='generation'"
                ).fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row["valor"]) if row else 0

    def get_recent_products(self, limit: int = 25) -> list[str]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT produto, MAX(id) AS last_id
                FROM bau_historico
                WHERE revertido=0
                GROUP BY produto
                ORDER BY last_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [row["produto"] for row in rows]

    def get_frequent_products(self, limit: int = 25) -> list[str]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT produto, COUNT(*) AS uses, MAX(id) AS last_id
                FROM bau_historico
                WHERE revertido=0
                GROUP BY produto
                ORDER BY uses DESC, last_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [row["produto"] for row in rows]

    def apply_operation(
        self,
        movement_type: str,
        items: list[tuple[str, int]],
        user_id: str,
        user_name: str,
        origin: str,
        operation_id: str | None = None,
        expected_generation: int | None = None,
    ) -> OperationResult:
        if movement_type not in {"entrada", "saida"}:
            raise ValueError("Tipo de movimentacao invalido")

        aggregated: dict[str, int] = {}
        for product, quantity in items:
            if product not in PRODUTO_CATEGORIA or quantity <= 0:
                raise ValueError("Produto ou quantidade invalida")
            aggregated[product] = aggregated.get(product, 0) + int(quantity)
        if not aggregated:
            raise ValueError("A operacao precisa de itens")

        operation_id = operation_id or uuid.uuid4().hex
        created_at = agora_str()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if expected_generation is not None:
                generation_row = conn.execute(
                    "SELECT valor FROM bau_meta WHERE chave='generation'"
                ).fetchone()
                current_generation = (
                    int(generation_row["valor"]) if generation_row else 0
                )
                if current_generation != expected_generation:
                    raise StaleOperationError(
                        "O bau foi zerado depois que a confirmacao foi aberta"
                    )
            try:
                conn.execute(
                    "INSERT INTO bau_operacoes "
                    "(operation_id, tipo, origem, user_id, user_nome, criado_em) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        operation_id,
                        movement_type,
                        origin,
                        user_id,
                        user_name,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateOperationError("Operacao ja processada") from exc

            current: dict[str, int] = {}
            for product in aggregated:
                row = conn.execute(
                    "SELECT quantidade FROM bau_estoque WHERE produto=?",
                    (product,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Produto nao cadastrado: {product}")
                current[product] = int(row["quantidade"])

            if movement_type == "saida":
                shortages = {
                    product: (quantity, current[product])
                    for product, quantity in aggregated.items()
                    if current[product] < quantity
                }
                if shortages:
                    raise StockInsufficientError(shortages)

            lines: list[MovementLine] = []
            delta_sign = 1 if movement_type == "entrada" else -1
            for product, quantity in aggregated.items():
                before = current[product]
                after = before + (delta_sign * quantity)
                conn.execute(
                    "UPDATE bau_estoque SET quantidade=? WHERE produto=?",
                    (after, product),
                )
                conn.execute(
                    """
                    INSERT INTO bau_historico (
                        produto, categoria, tipo, quantidade,
                        user_id, user_nome, criado_em,
                        operation_id, origem, revertido
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        product,
                        PRODUTO_CATEGORIA[product],
                        movement_type,
                        quantity,
                        user_id,
                        user_name,
                        created_at,
                        operation_id,
                        origin,
                    ),
                )
                lines.append(MovementLine(
                    product,
                    PRODUTO_CATEGORIA[product],
                    quantity,
                    before,
                    after,
                ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return OperationResult(
            operation_id,
            movement_type,
            origin,
            user_id,
            user_name,
            created_at,
            tuple(lines),
        )

    def get_last_undoable_operation(self, user_id: str) -> UndoOperation | None:
        with self._connection() as conn:
            operation = conn.execute(
                """
                SELECT operation_id, tipo, origem, criado_em, MAX(id) AS last_id
                FROM bau_historico
                WHERE user_id=? AND revertido=0
                GROUP BY operation_id, tipo, origem, criado_em
                ORDER BY last_id DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            if operation is None:
                return None
            rows = conn.execute(
                """
                SELECT produto, quantidade
                FROM bau_historico
                WHERE operation_id=? AND user_id=? AND revertido=0
                ORDER BY id
                """,
                (operation["operation_id"], user_id),
            ).fetchall()
        return UndoOperation(
            operation["operation_id"],
            operation["tipo"],
            operation["origem"],
            operation["criado_em"],
            tuple((row["produto"], int(row["quantidade"])) for row in rows),
        )

    def undo_items(
        self,
        operation_id: str,
        user_id: str,
        products: set[str],
    ) -> UndoResult:
        if not products:
            raise ValueError("Selecione pelo menos um produto")

        conn = self._connect()
        reverted: list[MovementLine] = []
        skipped: list[tuple[str, int, int]] = []
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT id, produto, categoria, tipo, quantidade
                FROM bau_historico
                WHERE operation_id=? AND user_id=? AND revertido=0
                ORDER BY id
                """,
                (operation_id, user_id),
            ).fetchall()
            selected_rows = [row for row in rows if row["produto"] in products]
            if not selected_rows:
                raise ValueError("A operacao nao possui itens disponiveis")

            reverted_at = agora_str()
            for row in selected_rows:
                product = row["produto"]
                quantity = int(row["quantidade"])
                stock_row = conn.execute(
                    "SELECT quantidade FROM bau_estoque WHERE produto=?",
                    (product,),
                ).fetchone()
                before = int(stock_row["quantidade"])
                if row["tipo"] == "entrada":
                    if before < quantity:
                        skipped.append((product, quantity, before))
                        continue
                    after = before - quantity
                else:
                    after = before + quantity

                conn.execute(
                    "UPDATE bau_estoque SET quantidade=? WHERE produto=?",
                    (after, product),
                )
                conn.execute(
                    "UPDATE bau_historico "
                    "SET revertido=1, revertido_em=?, revertido_por=? "
                    "WHERE id=?",
                    (reverted_at, user_id, row["id"]),
                )
                reverted.append(MovementLine(
                    product,
                    row["categoria"],
                    quantity,
                    before,
                    after,
                ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return UndoResult(operation_id, tuple(reverted), tuple(skipped))

    def clear_all(self) -> dict[str, int]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT produto, quantidade FROM bau_estoque WHERE quantidade > 0"
            ).fetchall()
            previous = {
                row["produto"]: int(row["quantidade"]) for row in rows
            }
            conn.execute("UPDATE bau_estoque SET quantidade=0")
            conn.execute("DELETE FROM bau_historico")
            conn.execute("DELETE FROM bau_operacoes")
            conn.execute(
                "UPDATE bau_meta SET valor=CAST(valor AS INTEGER) + 1 "
                "WHERE chave='generation'"
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return previous
