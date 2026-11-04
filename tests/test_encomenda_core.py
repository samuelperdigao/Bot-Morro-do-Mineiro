import logging
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from services.db_schema import ensure_schema
from services.encomenda_core import (
    STATUS,
    STATUS_FINAIS,
    TRANSICOES,
    EncomendaDesatualizadaError,
    EncomendaNaoEncontradaError,
    EncomendaRepository,
    TransicaoInvalidaError,
    format_brl,
    formatar_numero,
    parse_quantidade,
    parse_valor_centavos,
)


def _conectar(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


class ParseValorTests(unittest.TestCase):
    def test_formatos_aceitos(self):
        casos = {
            "1.500,00": 150000,
            "1500": 150000,
            "1500,5": 150050,
            "1500,50": 150050,
            "1.500": 150000,
            "R$ 1.500,00": 150000,
            "r$1.234.567,89": 123456789,
            " 0,50 ": 50,
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(parse_valor_centavos(texto), esperado)

    def test_formatos_rejeitados(self):
        for texto in ("0", "-5", "abc", "1,5,0", "", "   ", "0,00", "1.50", "1.5", "1500,", "1500,505", "R$"):
            with self.subTest(texto=texto):
                with self.assertRaises(ValueError):
                    parse_valor_centavos(texto)

    def test_valor_absurdo_e_rejeitado(self):
        with self.assertRaises(ValueError):
            parse_valor_centavos("999999999999999")


class ParseQuantidadeTests(unittest.TestCase):
    def test_validos(self):
        self.assertEqual(parse_quantidade("50"), 50)
        self.assertEqual(parse_quantidade(" 50 "), 50)

    def test_invalidos(self):
        for texto in ("0", "-3", "abc", "", "   ", "5,5", "1.000", None):
            with self.subTest(texto=texto):
                with self.assertRaises(ValueError):
                    parse_quantidade(texto)


class FormatacaoTests(unittest.TestCase):
    def test_format_brl(self):
        self.assertEqual(format_brl(150000), "R$ 1.500,00")
        self.assertEqual(format_brl(50), "R$ 0,50")
        self.assertEqual(format_brl(123456789), "R$ 1.234.567,89")

    def test_formatar_numero(self):
        self.assertEqual(formatar_numero(3), "#003")
        self.assertEqual(formatar_numero(42), "#042")
        self.assertEqual(formatar_numero(1234), "#1234")


class EncomendaRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "encomendas-test.db"
        self.conn = _conectar(self.db_path)
        ensure_schema(self.conn, self.db_path, logging.getLogger("test"))
        self.repo = EncomendaRepository(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def _criar(self, guild_id="guild-1", familia="Família Silva"):
        return self.repo.criar(guild_id, familia, 50, 150000, "08/06/2026", None, "user-1")

    def test_criar_grava_dados_e_evento(self):
        row = self.repo.criar("guild-1", "  Família Silva ", 50, 150000, "08/06/2026", "  ", "user-1")

        self.assertEqual(row["numero"], 1)
        self.assertEqual(row["familia"], "Família Silva")
        self.assertEqual(row["status"], "pendente")
        self.assertIsNone(row["observacao"])
        self.assertIsNone(row["responsavel_id"])
        eventos = self.repo.eventos(row["id"])
        self.assertEqual([(e["tipo"], e["para_status"], e["user_id"]) for e in eventos],
                         [("criada", "pendente", "user-1")])

    def test_criar_rejeita_quantidade_ou_valor_nao_positivos(self):
        with self.assertRaises(ValueError):
            self.repo.criar("guild-1", "F", 0, 100, "08/06/2026", None, "u")
        with self.assertRaises(ValueError):
            self.repo.criar("guild-1", "F", 1, -100, "08/06/2026", None, "u")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM encomendas").fetchone()[0], 0)

    def test_numeracao_sequencial_por_servidor(self):
        numeros = [
            (guild, self._criar(guild)["numero"])
            for guild in ("guild-1", "guild-1", "guild-2", "guild-1", "guild-2")
        ]
        self.assertEqual(numeros, [
            ("guild-1", 1), ("guild-1", 2), ("guild-2", 1), ("guild-1", 3), ("guild-2", 2),
        ])

    def test_obter_por_mensagem_pedidos(self):
        row = self._criar()
        self.repo.salvar_mensagem_pedidos(row["id"], 10, 20)

        achada = self.repo.obter_por_mensagem_pedidos(20)
        self.assertEqual(achada["id"], row["id"])
        self.assertEqual(achada["pedidos_channel_id"], "10")
        self.assertIsNone(self.repo.obter_por_mensagem_pedidos(999))

    def test_salvar_mensagem_arquivo(self):
        row = self._criar()
        self.repo.salvar_mensagem_arquivo(row["id"], 30, 40)
        atual = self.repo.obter(row["id"])
        self.assertEqual((atual["arquivo_channel_id"], atual["arquivo_message_id"]), ("30", "40"))

    def test_todas_as_transicoes_validas_e_invalidas(self):
        for origem in STATUS:
            for destino in STATUS:
                with self.subTest(origem=origem, destino=destino):
                    row = self._criar()
                    caminho = {
                        "pendente": [],
                        "em_producao": ["em_producao"],
                        "pronta": ["pronta"],
                        "entregue": ["entregue"],
                        "cancelada": ["cancelada"],
                    }[origem]
                    for passo in caminho:
                        self.repo.transitar(row["id"], passo, "lider")
                    permitido = destino in TRANSICOES.get(origem, set())
                    if permitido:
                        atual = self.repo.transitar(row["id"], destino, "lider")
                        self.assertEqual(atual["status"], destino)
                    else:
                        with self.assertRaises(TransicaoInvalidaError):
                            self.repo.transitar(row["id"], destino, "lider")
                        self.assertEqual(self.repo.obter(row["id"])["status"], origem)

    def test_estados_finais_nao_saem_e_nao_voltam(self):
        for final in STATUS_FINAIS:
            row = self._criar()
            self.repo.transitar(row["id"], final, "lider")
            for destino in STATUS:
                with self.subTest(final=final, destino=destino):
                    with self.assertRaises(TransicaoInvalidaError):
                        self.repo.transitar(row["id"], destino, "lider")

    def test_status_desconhecido_e_invalido(self):
        row = self._criar()
        with self.assertRaises(TransicaoInvalidaError):
            self.repo.transitar(row["id"], "sumiu", "lider")

    def test_encomenda_inexistente(self):
        with self.assertRaises(EncomendaNaoEncontradaError):
            self.repo.transitar(999, "pronta", "lider")

    def test_responsavel_e_finalizado_em(self):
        row = self._criar()
        self.repo.transitar(row["id"], "em_producao", "gerente-a")
        self.repo.transitar(row["id"], "pronta", "gerente-b")
        atual = self.repo.obter(row["id"])
        self.assertEqual(atual["responsavel_id"], "gerente-a")
        self.assertIsNone(atual["finalizado_em"])

        final = self.repo.transitar(row["id"], "entregue", "gerente-b")
        self.assertEqual(final["responsavel_id"], "gerente-a")
        self.assertIsNotNone(final["finalizado_em"])

    def test_responsavel_e_quem_fez_a_primeira_transicao_ao_pular_etapa(self):
        row = self._criar()
        atual = self.repo.transitar(row["id"], "pronta", "gerente-c")
        self.assertEqual(atual["responsavel_id"], "gerente-c")

    def test_desatualizada_quando_status_mudou_entre_leitura_e_escrita(self):
        row = self._criar()
        lido = self.repo.obter(row["id"])["status"]
        self.repo.transitar(row["id"], "em_producao", "gerente-a")

        with self.assertRaises(EncomendaDesatualizadaError):
            self.repo.transitar(row["id"], "entregue", "gerente-b", status_esperado=lido)
        atual = self.repo.obter(row["id"])
        self.assertEqual(atual["status"], "em_producao")
        self.assertEqual(len(self.repo.eventos(row["id"])), 2)

    def test_eventos_em_cada_transicao(self):
        row = self._criar()
        self.repo.transitar(row["id"], "em_producao", "g1")
        self.repo.transitar(row["id"], "pronta", "g2")
        self.repo.transitar(row["id"], "entregue", "g3")

        eventos = [
            (e["tipo"], e["de_status"], e["para_status"], e["user_id"])
            for e in self.repo.eventos(row["id"])
        ]
        self.assertEqual(eventos, [
            ("criada", None, "pendente", "user-1"),
            ("status", "pendente", "em_producao", "g1"),
            ("status", "em_producao", "pronta", "g2"),
            ("status", "pronta", "entregue", "g3"),
        ])

    def test_registrar_erro_grava_evento(self):
        row = self._criar()
        self.repo.registrar_erro(row["id"], "g1", "falhou")
        self.assertEqual(self.repo.eventos(row["id"])[-1]["tipo"], "erro")

    def test_listar_ativas(self):
        a = self._criar()
        b = self._criar()
        self._criar(guild_id="guild-2")
        self.repo.transitar(b["id"], "cancelada", "g1")

        self.assertEqual([r["id"] for r in self.repo.listar_ativas("guild-1")], [a["id"]])

    def test_excluir_remove_registro_e_eventos(self):
        row = self._criar()
        self.repo.excluir(row["id"])

        self.assertIsNone(self.repo.obter(row["id"]))
        self.assertEqual(self.repo.eventos(row["id"]), [])

    def test_concorrencia_exatamente_uma_transicao_vence(self):
        row = self._criar()
        encomenda_id = row["id"]
        total = 8
        barreira = threading.Barrier(total)

        def tentar(indice):
            conn = _conectar(self.db_path)
            try:
                repo = EncomendaRepository(conn)
                destino = "entregue" if indice % 2 else "cancelada"
                barreira.wait()
                try:
                    repo.transitar(encomenda_id, destino, f"user-{indice}", status_esperado="pendente")
                    return "ok"
                except (EncomendaDesatualizadaError, TransicaoInvalidaError):
                    return "perdeu"
            finally:
                conn.close()

        with ThreadPoolExecutor(max_workers=total) as executor:
            resultados = list(executor.map(tentar, range(total)))

        self.assertEqual(resultados.count("ok"), 1)
        self.assertEqual(resultados.count("perdeu"), total - 1)
        eventos_status = [e for e in self.repo.eventos(encomenda_id) if e["tipo"] == "status"]
        self.assertEqual(len(eventos_status), 1)
        self.assertIn(self.repo.obter(encomenda_id)["status"], STATUS_FINAIS)

    def test_concorrencia_sem_status_esperado_tambem_tem_um_vencedor(self):
        row = self._criar()
        total = 6
        barreira = threading.Barrier(total)

        def tentar(indice):
            conn = _conectar(self.db_path)
            try:
                barreira.wait()
                try:
                    EncomendaRepository(conn).transitar(row["id"], "em_producao", f"user-{indice}")
                    return "ok"
                except (EncomendaDesatualizadaError, TransicaoInvalidaError):
                    return "perdeu"
            finally:
                conn.close()

        with ThreadPoolExecutor(max_workers=total) as executor:
            resultados = list(executor.map(tentar, range(total)))

        self.assertEqual(resultados.count("ok"), 1)

    def test_criacao_concorrente_nao_repete_numero(self):
        total = 6
        barreira = threading.Barrier(total)

        def criar(indice):
            conn = _conectar(self.db_path)
            try:
                barreira.wait()
                return EncomendaRepository(conn).criar(
                    "guild-1", f"F{indice}", 1, 100, "08/06/2026", None, "u",
                )["numero"]
            finally:
                conn.close()

        with ThreadPoolExecutor(max_workers=total) as executor:
            numeros = list(executor.map(criar, range(total)))

        self.assertEqual(sorted(numeros), list(range(1, total + 1)))


class EncomendaSchemaTests(unittest.TestCase):
    def test_migracao_adiciona_canais_em_base_existente(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legado.db"
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                CREATE TABLE system_config (
                    guild_id TEXT NOT NULL,
                    sistema TEXT NOT NULL,
                    canal_interacao_id TEXT,
                    canal_log_id TEXT,
                    PRIMARY KEY (guild_id, sistema)
                );
                INSERT INTO system_config VALUES ('guild-1', 'encomenda', '111', '222');
                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
                );
                INSERT INTO schema_migrations VALUES (1, 'x', 'now'), (2, 'x', 'now'),
                    (3, 'x', 'now'), (4, 'x', 'now'), (5, 'x', 'now');
                """
            )
            ensure_schema(conn, path, logging.getLogger("test"))
            colunas = {row[1] for row in conn.execute("PRAGMA table_info(system_config)")}
            preservado = conn.execute(
                "SELECT canal_interacao_id, canal_log_id FROM system_config"
            ).fetchone()
            conn.close()

        self.assertTrue({"canal_pedidos_id", "canal_entregues_id"} <= colunas)
        self.assertEqual(preservado, ("111", "222"))


class EncomendaCanaisConfigTests(unittest.TestCase):
    def setUp(self):
        import services.db_service as db

        self.db = db
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = Path(self.tmp.name) / "canais.db"
        db._db_conn = None
        db.init_db()

    def tearDown(self):
        if self.db._db_conn is not None:
            self.db._db_conn.close()
        self.db._db_conn = self.old_conn
        self.db.DB_PATH = self.old_path
        self.tmp.cleanup()

    def test_canais_nao_sobrescrevem_interacao_e_log(self):
        db = self.db
        self.assertEqual(db.db_get_encomenda_canais("guild-1"), (None, None))

        db.db_set_system_config("guild-1", "encomenda", "111", "222")
        db.db_set_encomenda_canais("guild-1", "333", "444")
        db.db_set_system_config("guild-1", "encomenda", "555", "666")

        row = db.db_get_system_config("guild-1", "encomenda")
        self.assertEqual((row["canal_interacao_id"], row["canal_log_id"]), ("555", "666"))
        self.assertEqual(db.db_get_encomenda_canais("guild-1"), ("333", "444"))

    def test_canais_sem_config_previa(self):
        self.db.db_set_encomenda_canais("guild-2", "1", "2")
        row = self.db.db_get_system_config("guild-2", "encomenda")
        self.assertIsNone(row["canal_interacao_id"])
        self.assertEqual(self.db.db_get_encomenda_canais("guild-2"), ("1", "2"))


if __name__ == "__main__":
    unittest.main()
