import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from cogs.cache_fivem import (
    COMANDO_LIMPAR_CACHE,
    CUSTOM_ID_COPIAR,
    FLAG_COMPONENTS_V2,
    CacheFivemCog,
    CopiarComandoView,
    montar_payload,
)

BOT_ID = 111


def _percorrer(componentes):
    for comp in componentes:
        yield comp
        yield from _percorrer(comp.get("components", []))


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.payload = montar_payload()
        self.todos = list(_percorrer(self.payload["components"]))

    def test_usa_components_v2_sem_content_nem_embeds(self):
        self.assertTrue(self.payload["flags"] & FLAG_COMPONENTS_V2)
        self.assertNotIn("content", self.payload)
        self.assertNotIn("embeds", self.payload)

    def test_raiz_e_um_container(self):
        self.assertEqual(len(self.payload["components"]), 1)
        self.assertEqual(self.payload["components"][0]["type"], 17)

    def test_comando_aparece_inteiro_e_dentro_do_limite_do_discord(self):
        textos = [c["content"] for c in self.todos if c["type"] == 10]
        self.assertTrue(any(COMANDO_LIMPAR_CACHE in t for t in textos))
        self.assertTrue(all(len(t) <= 4000 for t in textos))
        self.assertLessEqual(len(json.dumps(self.payload)), 6000 * 4)

    def test_botao_tem_custom_id_e_view_persistente_usa_o_mesmo(self):
        botoes = [c for c in self.todos if c["type"] == 2]
        self.assertEqual([b["custom_id"] for b in botoes], [CUSTOM_ID_COPIAR])
        async def criar():
            return CopiarComandoView()

        view = asyncio.run(criar())
        self.assertIsNone(view.timeout)
        self.assertEqual([i.custom_id for i in view.children], [CUSTOM_ID_COPIAR])

    def test_botao_responde_ephemeral_com_o_comando(self):
        interaction = SimpleNamespace(response=SimpleNamespace(send_message=AsyncMock()))

        async def executar():
            view = CopiarComandoView()
            await view.copiar.callback(interaction)

        asyncio.run(executar())
        args, kwargs = interaction.response.send_message.call_args
        self.assertIn(COMANDO_LIMPAR_CACHE, args[0])
        self.assertTrue(kwargs["ephemeral"])
        self.assertLessEqual(len(args[0]), 2000)


class GarantirPainelTests(unittest.TestCase):
    def _cog(self, recentes):
        http = MagicMock()
        http.logs_from = AsyncMock(return_value=recentes)
        http.request = AsyncMock(return_value={"id": "999"})
        bot = SimpleNamespace(http=http, user=SimpleNamespace(id=BOT_ID))
        cog = CacheFivemCog.__new__(CacheFivemCog)
        cog.bot = bot
        cog._lock = asyncio.Lock()
        cog._renomear_canal = AsyncMock()
        return cog, http

    def test_cria_e_renomeia_quando_nao_existe_painel(self):
        cog, http = self._cog([{"id": "1", "author": {"id": str(BOT_ID)}, "flags": 0, "components": []}])
        self.assertEqual(asyncio.run(cog.garantir_painel()), "criado")
        route = http.request.call_args.args[0]
        self.assertEqual(route.method, "POST")
        cog._renomear_canal.assert_awaited_once()

    def test_edita_no_lugar_quando_painel_ja_existe(self):
        painel = {
            "id": "42",
            "author": {"id": str(BOT_ID)},
            "flags": FLAG_COMPONENTS_V2,
            "components": montar_payload()["components"],
        }
        cog, http = self._cog([painel])
        self.assertEqual(asyncio.run(cog.garantir_painel()), "editado")
        route = http.request.call_args.args[0]
        self.assertEqual(route.method, "PATCH")
        self.assertIn("/42", route.url)
        cog._renomear_canal.assert_not_awaited()

    def test_ignora_mensagem_de_outro_autor_com_mesmo_botao(self):
        alheia = {
            "id": "7",
            "author": {"id": "222"},
            "flags": FLAG_COMPONENTS_V2,
            "components": montar_payload()["components"],
        }
        cog, http = self._cog([alheia])
        self.assertEqual(asyncio.run(cog.garantir_painel()), "criado")


if __name__ == "__main__":
    unittest.main()
