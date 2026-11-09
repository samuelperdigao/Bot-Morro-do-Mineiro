import gzip
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.extensions import COG_EXTENSIONS
from services.backup_service import BANCOS, backup_banco


class BackupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.origem = self.dir / "pasta com espaço" / "farm.db"
        self.origem.parent.mkdir()
        conn = sqlite3.connect(self.origem)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE t (v INTEGER)")
        conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(100)])
        conn.commit()
        conn.close()

    def tearDown(self):
        self._tmp.cleanup()

    def test_backup_gera_copia_integra_e_compactada(self):
        destino = self.dir / "backups"
        resultado = backup_banco("farm", self.origem, destino)
        self.assertTrue(resultado.caminho.name.endswith(".db.gz"))

        restaurado = self.dir / "restaurado.db"
        with gzip.open(resultado.caminho, "rb") as f_in:
            restaurado.write_bytes(f_in.read())
        conn = sqlite3.connect(restaurado)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM t").fetchone()[0], 100)
        conn.close()
        self.assertEqual(list(destino.glob("*.db")), [])

    def test_retencao_mantem_as_mais_recentes(self):
        destino = self.dir / "backups"
        base = datetime(2026, 1, 1)
        for i in range(5):
            backup_banco("farm", self.origem, destino, retencao=3, agora=base + timedelta(days=i))
        copias = sorted(p.name for p in destino.glob("farm-*.db.gz"))
        self.assertEqual(len(copias), 3)
        self.assertIn("farm-20260105-000000.db.gz", copias)
        self.assertNotIn("farm-20260101-000000.db.gz", copias)

    def test_retencao_nao_apaga_backups_do_deploy(self):
        destino = self.dir / "backups"
        destino.mkdir()
        predeploy = destino / "predeploy-farm-20200101-000000.db.gz"
        predeploy.write_bytes(b"x")
        backup_banco("farm", self.origem, destino, retencao=1)
        self.assertTrue(predeploy.exists())

    def test_banco_inexistente_e_ignorado(self):
        self.assertIsNone(backup_banco("x", self.dir / "nao_existe.db", self.dir / "b"))


class BackupConfigTests(unittest.TestCase):
    def test_bancos_do_bot(self):
        self.assertEqual(set(BANCOS), {"farm", "bau"})
        self.assertEqual(BANCOS["bau"].name, "bau.db")

    def test_cog_de_backup_carregado(self):
        self.assertIn("cogs.backup", COG_EXTENSIONS)

    def test_backup_agora_restrito_a_administradores(self):
        from cogs.backup import BackupCog

        self.assertTrue(BackupCog.backup_agora.default_permissions.administrator)


if __name__ == "__main__":
    unittest.main()
