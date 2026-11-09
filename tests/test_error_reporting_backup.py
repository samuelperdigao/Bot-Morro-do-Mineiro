import asyncio
import gzip
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from discord.ext import tasks

from core import error_reporting
from core.error_reporting import _deve_avisar, proteger_loop
from services.backup_service import backup_banco


class AvisoRateLimitTests(unittest.TestCase):
    def setUp(self):
        error_reporting._ultimos_avisos.clear()

    def test_mesmo_erro_so_avisa_uma_vez_na_janela(self):
        self.assertTrue(_deve_avisar("x", agora=1000))
        self.assertFalse(_deve_avisar("x", agora=1000 + 10))
        self.assertTrue(_deve_avisar("x", agora=1000 + error_reporting.JANELA_AVISO_SEGUNDOS + 1))
        self.assertTrue(_deve_avisar("y", agora=1000 + 10))


class ProtegerLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_task_que_falha_e_reiniciada(self):
        execucoes = []

        @tasks.loop(seconds=0.01, count=None)
        async def minha_task():
            execucoes.append(1)
            if len(execucoes) == 1:
                raise ValueError("falha simulada")
            minha_task.stop()

        proteger_loop(minha_task, "teste", atraso_reinicio=0.05)
        minha_task.start()
        for _ in range(100):
            await asyncio.sleep(0.02)
            if len(execucoes) >= 2 and not minha_task.is_running():
                break
        self.assertGreaterEqual(len(execucoes), 2)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.origem = self.dir / "farm.db"
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

    def test_banco_inexistente_e_ignorado(self):
        self.assertIsNone(backup_banco("x", self.dir / "nao_existe.db", self.dir / "b"))


if __name__ == "__main__":
    unittest.main()
