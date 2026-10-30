import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "token-de-teste")
os.environ.setdefault("APPLICATION_ID", "1")

import discord

import services.db_service as db
from cogs.ausencia import (
    Ausencia,
    AusenciaModal,
    CANAL_LEGADO_ID,
    migrar_canal_legado,
    migrar_json_legado,
)


def _iso(delta_dias: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=delta_dias)).isoformat()


def _ausencia(fim: str, **extras) -> dict:
    return {"nome": "Membro", "dias": 1, "motivo": "Viagem", "inicio": _iso(-1), "fim": fim, **extras}


def _guild(guild_id: int = 1, *, tem_canal_legado: bool = False, membros: dict | None = None):
    return SimpleNamespace(
        id=guild_id,
        get_channel=lambda channel_id: object()
        if tem_canal_legado and channel_id == CANAL_LEGADO_ID
        else None,
        get_member=(membros or {}).get,
    )


class AusenciaDbTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.old_path = db.DB_PATH
        self.old_conn = db._db_conn
        db.DB_PATH = self.dir / "ausencia.db"
        db._db_conn = None
        db.init_db()

    def tearDown(self):
        if db._db_conn is not None:
            db._db_conn.close()
        db._db_conn = self.old_conn
        db.DB_PATH = self.old_path
        self.tmp.cleanup()


class HistoricoTests(AusenciaDbTestCase):
    def test_duas_ausencias_preservam_historico_e_ativa_e_a_mais_recente(self):
        primeira = db.db_ausencia_set("1", "10", _ausencia(_iso(2), motivo="Primeira"))
        segunda = db.db_ausencia_set("1", "10", _ausencia(_iso(5), motivo="Segunda"))

        self.assertNotEqual(primeira, segunda)
        self.assertEqual(len(db.db_ausencias_todos("1")), 2)
        ativos = db.db_ausencias_ativos("1")
        self.assertEqual([row["motivo"] for row in ativos], ["Segunda"])
        self.assertEqual(db.db_ausencia_get("1", "10")["id"], segunda)

    def test_ativas_sao_isoladas_por_guild(self):
        db.db_ausencia_set("1", "10", _ausencia(_iso(2)))
        db.db_ausencia_set("2", "20", _ausencia(_iso(2)))

        self.assertEqual([row["user_id"] for row in db.db_ausencias_ativos("1")], ["10"])

    def test_tabela_antiga_nao_recebe_novos_registros(self):
        db.db_ausencia_set("1", "10", _ausencia(_iso(2)))

        total = db.get_conn().execute("SELECT COUNT(*) FROM ausencias").fetchone()[0]
        self.assertEqual(total, 0)

    def test_atualizacoes_por_id_nao_alteram_o_registro_anterior(self):
        primeira = db.db_ausencia_set("1", "10", _ausencia(_iso(-1)))
        segunda = db.db_ausencia_set("1", "10", _ausencia(_iso(2)))

        db.db_ausencia_atualizar_message_id(segunda, "99")
        db.db_ausencia_marcar_avisado(primeira)

        rows = {row["id"]: row for row in db.db_ausencias_todos("1")}
        self.assertIsNone(rows[primeira]["message_id"])
        self.assertEqual(rows[segunda]["message_id"], "99")
        self.assertEqual(rows[primeira]["avisado"], 1)
        self.assertEqual(rows[segunda]["avisado"], 0)


class DatasTests(AusenciaDbTestCase):
    def test_data_sem_fuso_e_tratada_como_utc(self):
        self.assertEqual(
            db.db_ausencia_parse_data("2026-10-01T10:00:00"),
            datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
        )

    def test_data_com_fuso_e_preservada(self):
        self.assertEqual(
            db.db_ausencia_parse_data("2026-10-01T10:00:00-03:00"),
            datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc),
        )

    def test_data_invalida_ou_vazia_retorna_none(self):
        for valor in (None, "", "ontem"):
            with self.subTest(valor=valor):
                self.assertIsNone(db.db_ausencia_parse_data(valor))

    def test_comparacao_nao_depende_do_texto_da_data(self):
        # Em fusos diferentes, a ordem do texto ISO não acompanha a ordem real.
        agora = datetime.now(timezone.utc)
        futuro_outro_fuso = (agora + timedelta(hours=1)).astimezone(timezone(timedelta(hours=-3)))
        passado_outro_fuso = (agora - timedelta(hours=1)).astimezone(timezone(timedelta(hours=9)))
        db.db_ausencia_set("1", "10", _ausencia(futuro_outro_fuso.isoformat()))
        db.db_ausencia_set("1", "20", _ausencia(passado_outro_fuso.isoformat()))

        self.assertEqual([row["user_id"] for row in db.db_ausencias_ativos("1")], ["10"])
        self.assertEqual(
            [row["user_id"] for row in db.db_ausencias_vencidas_sem_aviso("1")], ["20"]
        )

    def test_legado_sem_fuso_entra_em_ativas_e_vencidas(self):
        agora = datetime.now(timezone.utc).replace(tzinfo=None)
        db.db_ausencia_set("1", "10", _ausencia((agora + timedelta(hours=1)).isoformat()))
        db.db_ausencia_set("1", "20", _ausencia((agora - timedelta(hours=1)).isoformat()))

        self.assertEqual([row["user_id"] for row in db.db_ausencias_ativos("1")], ["10"])
        self.assertEqual(
            [row["user_id"] for row in db.db_ausencias_vencidas_sem_aviso("1")], ["20"]
        )


class MigracaoJsonTests(AusenciaDbTestCase):
    def _escrever_json(self, nome: str = "ausencias.json", conteudo: str | None = None) -> Path:
        arquivo = self.dir / nome
        arquivo.write_text(
            conteudo
            if conteudo is not None
            else json.dumps(
                {
                    "10": _ausencia("2026-10-03T10:00:00", inicio="2026-10-01T10:00:00", avisado=True),
                    "20": _ausencia(_iso(3), inicio=_iso(-1), avisado=False),
                }
            ),
            encoding="utf-8",
        )
        return arquivo

    def test_migracao_duas_vezes_nao_duplica_e_renomeia(self):
        arquivo = self._escrever_json()
        copia = arquivo.read_text(encoding="utf-8")

        migrar_json_legado([_guild()], (arquivo,))

        self.assertFalse(arquivo.exists())
        self.assertTrue((self.dir / "ausencias.json.migrated").exists())
        self.assertEqual(len(db.db_ausencias_todos("1")), 2)

        # Simula um arquivo restaurado: a rotina não duplica nem sobrescreve o .migrated.
        arquivo.write_text(copia, encoding="utf-8")
        migrar_json_legado([_guild()], (arquivo,))
        migrar_json_legado([_guild()], (arquivo,))

        self.assertEqual(len(db.db_ausencias_todos("1")), 2)
        self.assertTrue(arquivo.exists())

    def test_ausencia_ja_vencida_no_legado_nao_gera_lembrete(self):
        arquivo = self._escrever_json(
            conteudo=json.dumps({"10": _ausencia("2026-01-01T10:00:00", avisado=False)})
        )

        migrar_json_legado([_guild()], (arquivo,))

        self.assertEqual(db.db_ausencias_vencidas_sem_aviso("1"), [])
        self.assertEqual(db.db_ausencias_todos("1")[0]["avisado"], 1)

    def test_guild_do_canal_legado_tem_prioridade(self):
        arquivo = self._escrever_json()

        migrar_json_legado([_guild(1), _guild(2, tem_canal_legado=True)], (arquivo,))

        self.assertEqual(db.db_ausencias_todos("1"), [])
        self.assertEqual(len(db.db_ausencias_todos("2")), 2)

    def test_varias_guilds_sem_canal_legado_nao_migra_nem_renomeia(self):
        arquivo = self._escrever_json()

        migrar_json_legado([_guild(1), _guild(2)], (arquivo,))

        self.assertTrue(arquivo.exists())
        self.assertEqual(db.db_ausencias_todos("1"), [])
        self.assertEqual(db.db_ausencias_todos("2"), [])

    def test_json_invalido_nao_renomeia_nem_grava(self):
        for conteudo in ("{quebrado", "[1, 2]", '{"10": "texto"}'):
            with self.subTest(conteudo=conteudo):
                arquivo = self._escrever_json(conteudo=conteudo)

                migrar_json_legado([_guild()], (arquivo,))

                self.assertTrue(arquivo.exists())
                self.assertEqual(db.db_ausencias_todos("1"), [])

    def test_db_migrate_from_json_usa_a_tabela_nova_e_mantem_o_arquivo(self):
        arquivo = self._escrever_json()
        canal_map = self.dir / "channel_map.json"

        self.assertEqual(db.db_migrate_from_json("1", canal_map, arquivo), (0, 2))
        self.assertEqual(db.db_migrate_from_json("1", canal_map, arquivo), (0, 0))

        self.assertTrue(arquivo.exists())
        self.assertEqual(len(db.db_ausencias_todos("1")), 2)
        total_antiga = db.get_conn().execute("SELECT COUNT(*) FROM ausencias").fetchone()[0]
        self.assertEqual(total_antiga, 0)


class CanalLegadoTests(AusenciaDbTestCase):
    def test_preenche_somente_quando_nulo(self):
        db.db_set_guild_config("2", canal_ausencias_id="555")

        migrar_canal_legado(
            [
                _guild(1, tem_canal_legado=True),
                _guild(2, tem_canal_legado=True),
                _guild(3),
            ]
        )

        self.assertEqual(db.db_get_guild_config("1")["canal_ausencias_id"], str(CANAL_LEGADO_ID))
        self.assertEqual(db.db_get_guild_config("2")["canal_ausencias_id"], "555")
        self.assertIsNone(db.db_get_guild_config("3"))


class AvisoVencidasTests(AusenciaDbTestCase, unittest.IsolatedAsyncioTestCase):
    def _cog(self, *guilds):
        por_id = {guild.id: guild for guild in guilds}
        cog = Ausencia.__new__(Ausencia)
        cog.bot = SimpleNamespace(get_guild=por_id.get)
        return cog

    async def test_vencida_recebe_dm_e_e_marcada_como_avisada(self):
        db.db_set_guild_config("1", canal_ausencias_id="1")
        ausencia_id = db.db_ausencia_set("1", "10", _ausencia(_iso(-1)))
        membro = SimpleNamespace(send=AsyncMock())

        await self._cog(_guild(1, membros={10: membro}))._avisar_vencidas()

        membro.send.assert_awaited_once()
        self.assertEqual(db.db_ausencia_get("1", "10")["id"], ausencia_id)
        self.assertEqual(db.db_ausencia_get("1", "10")["avisado"], 1)
        self.assertEqual(db.db_ausencias_vencidas_sem_aviso("1"), [])

    async def test_dm_bloqueada_continua_marcando(self):
        db.db_set_guild_config("1", canal_ausencias_id="1")
        db.db_ausencia_set("1", "10", _ausencia(_iso(-1)))
        erro = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "bloqueado")
        membro = SimpleNamespace(send=AsyncMock(side_effect=erro))

        await self._cog(_guild(1, membros={10: membro}))._avisar_vencidas()

        self.assertEqual(db.db_ausencia_get("1", "10")["avisado"], 1)

    async def test_falha_temporaria_de_dm_tenta_de_novo_no_proximo_ciclo(self):
        db.db_set_guild_config("1", canal_ausencias_id="1")
        db.db_ausencia_set("1", "10", _ausencia(_iso(-1)))
        erro = discord.HTTPException(SimpleNamespace(status=503, reason="Indisponível"), "erro")
        membro = SimpleNamespace(send=AsyncMock(side_effect=erro))

        await self._cog(_guild(1, membros={10: membro}))._avisar_vencidas()

        self.assertEqual(db.db_ausencia_get("1", "10")["avisado"], 0)

    async def test_duas_vencidas_no_mesmo_ciclo_geram_uma_dm(self):
        db.db_set_guild_config("1", canal_ausencias_id="1")
        db.db_ausencia_set("1", "10", _ausencia(_iso(-2)))
        db.db_ausencia_set("1", "10", _ausencia(_iso(-1)))
        membro = SimpleNamespace(send=AsyncMock())

        await self._cog(_guild(1, membros={10: membro}))._avisar_vencidas()

        membro.send.assert_awaited_once()
        self.assertEqual(db.db_ausencias_vencidas_sem_aviso("1"), [])

    async def test_ausencia_substituida_por_outra_ativa_nao_gera_dm(self):
        db.db_set_guild_config("1", canal_ausencias_id="1")
        vencida = db.db_ausencia_set("1", "10", _ausencia(_iso(-1)))
        ativa = db.db_ausencia_set("1", "10", _ausencia(_iso(3)))
        membro = SimpleNamespace(send=AsyncMock())

        await self._cog(_guild(1, membros={10: membro}))._avisar_vencidas()

        membro.send.assert_not_awaited()
        rows = {row["id"]: row for row in db.db_ausencias_todos("1")}
        self.assertEqual(rows[vencida]["avisado"], 1)
        self.assertEqual(rows[ativa]["avisado"], 0)

    async def test_guild_e_resolvida_pelo_id_da_linha(self):
        db.db_set_guild_config("1", canal_ausencias_id="1")
        db.db_set_guild_config("2", canal_ausencias_id="2")
        db.db_ausencia_set("2", "10", _ausencia(_iso(-1)))
        membro_errado = SimpleNamespace(send=AsyncMock())
        membro_certo = SimpleNamespace(send=AsyncMock())

        await self._cog(
            _guild(1, membros={10: membro_errado}),
            _guild(2, membros={10: membro_certo}),
        )._avisar_vencidas()

        membro_errado.send.assert_not_awaited()
        membro_certo.send.assert_awaited_once()


class ModalAusenciaTests(AusenciaDbTestCase, unittest.IsolatedAsyncioTestCase):
    def _interaction(self, canal):
        return SimpleNamespace(
            guild_id=1,
            guild=SimpleNamespace(get_channel=lambda _id: canal),
            client=object(),
            user=SimpleNamespace(
                id=10,
                display_name="Membro",
                mention="<@10>",
                display_avatar=SimpleNamespace(url="https://example.com/a.png"),
            ),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

    def _modal(self):
        modal = AusenciaModal()
        modal.dias._value = "2"
        modal.motivo._value = "Viagem"
        return modal

    async def test_canal_inexistente_nao_grava_registro(self):
        db.db_set_guild_config("1", canal_ausencias_id="500")
        interaction = self._interaction(None)

        await self._modal().on_submit(interaction)

        self.assertEqual(db.db_ausencias_todos("1"), [])
        interaction.followup.send.assert_awaited_once()

    async def test_falha_ao_publicar_nao_deixa_registro(self):
        db.db_set_guild_config("1", canal_ausencias_id="500")
        canal = SimpleNamespace(id=500, mention="<#500>", send=AsyncMock(side_effect=RuntimeError("falhou")))

        with self.assertRaises(RuntimeError):
            await self._modal().on_submit(self._interaction(canal))

        self.assertEqual(db.db_ausencias_todos("1"), [])

    async def test_sucesso_grava_data_com_fuso_canal_e_mensagem(self):
        db.db_set_guild_config("1", canal_ausencias_id="500")
        canal = SimpleNamespace(
            id=500,
            mention="<#500>",
            send=AsyncMock(return_value=SimpleNamespace(id=777)),
        )

        with patch("cogs.ausencia.send_log", AsyncMock()):
            await self._modal().on_submit(self._interaction(canal))

        row = db.db_ausencia_get("1", "10")
        self.assertEqual(row["message_id"], "777")
        self.assertEqual(row["canal_id"], "500")
        self.assertIsNotNone(datetime.fromisoformat(row["fim"]).tzinfo)


if __name__ == "__main__":
    unittest.main()
