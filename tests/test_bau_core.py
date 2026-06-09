import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cogs.bau_core import (
    CATEGORIAS,
    BauRepository,
    StaleOperationError,
    StockInsufficientError,
    parse_batch_text,
)


class BauParserTests(unittest.TestCase):
    def test_parser_normalizes_names_and_sums_duplicates(self):
        result = parse_batch_text(
            "Colete: 10\n"
            "  colete : 5\n"
            "LANÇA PERFUME: 2\n"
            "dinheiro   sujo: 100.000"
        )

        self.assertTrue(result.valid)
        self.assertEqual(
            dict(result.items),
            {
                "Colete": 15,
                "Lanca Perfume": 2,
                "Dinheiro Sujo": 100000,
            },
        )

    def test_parser_blocks_unknown_product_and_suggests_match(self):
        result = parse_batch_text("Coleti: 10")

        self.assertFalse(result.valid)
        self.assertEqual(len(result.issues), 1)
        self.assertIn("Colete", result.issues[0].suggestions)

    def test_parser_accepts_the_complete_catalog(self):
        products = [
            product
            for category_products in CATEGORIAS.values()
            for product in category_products
        ]
        result = parse_batch_text(
            "\n".join(f"{product}: 1" for product in products)
        )

        self.assertTrue(result.valid)
        self.assertEqual(len(result.items), 78)


class BauRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "bau-test.db"
        self.repo = BauRepository(self.db_path)
        self.repo.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initialize_seeds_all_products(self):
        self.assertEqual(len(self.repo.get_stock()), 78)
        self.assertTrue(all(value == 0 for value in self.repo.get_stock().values()))

    def test_batch_is_atomic_when_one_withdrawal_is_insufficient(self):
        self.repo.apply_operation(
            "entrada",
            [("Colete", 10), ("5mm", 20)],
            "1",
            "Teste",
            "lote",
        )

        with self.assertRaises(StockInsufficientError):
            self.repo.apply_operation(
                "saida",
                [("Colete", 5), ("5mm", 30)],
                "1",
                "Teste",
                "lote",
            )

        stock = self.repo.get_stock()
        self.assertEqual(stock["Colete"], 10)
        self.assertEqual(stock["5mm"], 20)

    def test_concurrent_withdrawals_never_make_stock_negative(self):
        self.repo.apply_operation(
            "entrada",
            [("Colete", 10)],
            "1",
            "Teste",
            "individual",
        )

        def withdraw(operation_id):
            try:
                self.repo.apply_operation(
                    "saida",
                    [("Colete", 7)],
                    operation_id,
                    operation_id,
                    "rapido",
                    operation_id=operation_id,
                )
                return "ok"
            except StockInsufficientError:
                return "insufficient"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(withdraw, ("op-a", "op-b")))

        self.assertCountEqual(results, ["ok", "insufficient"])
        self.assertEqual(self.repo.get_quantity("Colete"), 3)

    def test_recent_and_frequent_products_are_global(self):
        self.repo.apply_operation(
            "entrada", [("Colete", 1)], "1", "A", "rapido"
        )
        self.repo.apply_operation(
            "entrada", [("5mm", 1)], "2", "B", "rapido"
        )
        self.repo.apply_operation(
            "entrada", [("Colete", 1)], "3", "C", "rapido"
        )

        self.assertEqual(self.repo.get_recent_products()[:2], ["Colete", "5mm"])
        self.assertEqual(self.repo.get_frequent_products()[:2], ["Colete", "5mm"])

    def test_selective_undo_reverts_valid_items_and_skips_invalid_ones(self):
        original = self.repo.apply_operation(
            "entrada",
            [("Colete", 10), ("9mm", 5)],
            "owner",
            "Owner",
            "lote",
        )
        self.repo.apply_operation(
            "saida",
            [("Colete", 8)],
            "other",
            "Other",
            "rapido",
        )

        result = self.repo.undo_items(
            original.operation_id,
            "owner",
            {"Colete", "9mm"},
        )

        self.assertEqual([line.produto for line in result.reverted], ["9mm"])
        self.assertEqual(result.skipped, (("Colete", 10, 2),))
        self.assertEqual(self.repo.get_quantity("Colete"), 2)
        self.assertEqual(self.repo.get_quantity("9mm"), 0)

        remaining = self.repo.get_last_undoable_operation("owner")
        self.assertIsNotNone(remaining)
        self.assertEqual(remaining.items, (("Colete", 10),))

    def test_clear_zeros_stock_and_removes_history_features(self):
        self.repo.apply_operation(
            "entrada",
            [("Colete", 10), ("5mm", 20)],
            "1",
            "Teste",
            "lote",
        )

        previous = self.repo.clear_all()

        self.assertEqual(previous, {"Colete": 10, "5mm": 20})
        self.assertTrue(all(value == 0 for value in self.repo.get_stock().values()))
        self.assertEqual(self.repo.get_recent_products(), [])
        self.assertEqual(self.repo.get_frequent_products(), [])
        self.assertIsNone(self.repo.get_last_undoable_operation("1"))

    def test_clear_invalidates_pending_confirmations(self):
        generation = self.repo.get_generation()
        self.repo.clear_all()

        with self.assertRaises(StaleOperationError):
            self.repo.apply_operation(
                "entrada",
                [("Colete", 10)],
                "1",
                "Teste",
                "rapido",
                expected_generation=generation,
            )

        self.assertEqual(self.repo.get_quantity("Colete"), 0)

    def test_initialize_migrates_legacy_history(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        conn = sqlite3.connect(legacy_path)
        try:
            conn.executescript("""
                CREATE TABLE bau_estoque (
                    produto TEXT PRIMARY KEY,
                    categoria TEXT NOT NULL,
                    quantidade INTEGER DEFAULT 0
                );
                CREATE TABLE bau_historico (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    produto TEXT NOT NULL,
                    categoria TEXT NOT NULL,
                    tipo TEXT NOT NULL,
                    quantidade INTEGER NOT NULL,
                    user_id TEXT NOT NULL,
                    user_nome TEXT NOT NULL,
                    criado_em TEXT NOT NULL
                );
                INSERT INTO bau_historico (
                    produto, categoria, tipo, quantidade,
                    user_id, user_nome, criado_em
                ) VALUES (
                    'Colete', 'Itens Gerais', 'entrada', 2,
                    'legacy-user', 'Legacy', '01/01/2026 10:00:00'
                );
            """)
            conn.commit()
        finally:
            conn.close()

        legacy_repo = BauRepository(legacy_path)
        legacy_repo.initialize()
        operation = legacy_repo.get_last_undoable_operation("legacy-user")

        self.assertIsNotNone(operation)
        self.assertEqual(operation.operation_id, "legacy-1")
        self.assertEqual(operation.items, (("Colete", 2),))


if __name__ == "__main__":
    unittest.main()
