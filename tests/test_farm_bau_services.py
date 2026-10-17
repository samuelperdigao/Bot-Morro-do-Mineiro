import tempfile
import unittest
from pathlib import Path

import services.db_service as db
from services.bau_service import BauService
from services.farm_service import farm_service


class FarmAndBauServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = Path(self.tmp.name) / "farm.db"
        db._db_conn = None
        db.init_db()

    def tearDown(self):
        if db._db_conn is not None:
            db._db_conn.close()
        db._db_conn = self.old_conn
        db.DB_PATH = self.old_path
        self.tmp.cleanup()

    def test_farm_service_reads_from_the_current_temporary_database(self):
        self.assertIsNone(farm_service.get_meta("guild-1", "2026-W25"))
        self.assertTrue(farm_service.current_week_id())

    def test_bau_service_keeps_db_and_panel_refs_explicit_and_isolated(self):
        storage_root = Path(self.tmp.name) / "bau-storage"
        storage_root.mkdir()
        service = BauService(storage_root)
        self.assertEqual(service.load_panel_reference(service.paths.panel_reference), (None, None))

        service.repository.initialize()
        result = service.repository.apply_operation(
            "entrada",
            [("Colete", 2)],
            "user-1",
            "Membro",
            "teste",
            operation_id="phase6-test",
        )
        self.assertEqual(result.lines[0].estoque_depois, 2)

        service.save_panel_reference(service.paths.panel_reference, 10, 20)
        self.assertEqual(
            service.load_panel_reference(service.paths.panel_reference),
            (10, 20),
        )
        self.assertEqual(service.paths.managers_panel_reference.name, "bau_gerentes_painel.json")


if __name__ == "__main__":
    unittest.main()
