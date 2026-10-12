import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from cogs.farm import (
    FarmCog,
    _meta_aprovada_anexo,
    _meta_aprovada_asset,
    _meta_aprovada_filename,
)


def _fake_membro():
    return SimpleNamespace(
        id=1234,
        mention="<@1234>",
        display_name="Mineiro",
        display_avatar=SimpleNamespace(url="https://cdn.example/avatar.png"),
        send=AsyncMock(),
    )


def _fake_guild(membro):
    return SimpleNamespace(id=99, get_member=lambda _id: membro)


class MetaAprovadaArteTests(unittest.TestCase):
    def test_arte_disponivel_no_repositorio(self):
        self.assertIsNotNone(_meta_aprovada_asset())

    def test_cada_chamada_gera_um_anexo_novo(self):
        primeiro = _meta_aprovada_anexo()
        segundo = _meta_aprovada_anexo()
        self.assertIsNotNone(primeiro)
        self.assertIsNotNone(segundo)
        self.assertIsNot(primeiro, segundo)
        self.assertEqual(primeiro.filename, _meta_aprovada_filename())
        self.assertEqual(segundo.filename, _meta_aprovada_filename())
        for anexo in (primeiro, segundo):
            anexo.close()


class NotificarAprovacaoTests(unittest.IsolatedAsyncioTestCase):
    async def test_envia_na_pasta_privada_com_a_arte(self):
        membro = _fake_membro()
        guild = _fake_guild(membro)
        pasta = SimpleNamespace(id=777, send=AsyncMock())
        cog = SimpleNamespace(_resolver_pasta_privada=AsyncMock(return_value=pasta))

        await FarmCog._notificar_aprovacao(
            cog, guild, "1234", membro, antecipada=False
        )

        pasta.send.assert_awaited_once()
        membro.send.assert_not_awaited()
        args, kwargs = pasta.send.await_args
        self.assertEqual(args[0], membro.mention)
        arquivos = kwargs["files"]
        self.assertEqual(len(arquivos), 1)
        self.assertEqual(
            kwargs["embed"].image.url, f"attachment://{arquivos[0].filename}"
        )
        arquivos[0].close()

    async def test_cai_na_dm_quando_a_pasta_nao_existe(self):
        membro = _fake_membro()
        guild = _fake_guild(membro)
        cog = SimpleNamespace(_resolver_pasta_privada=AsyncMock(return_value=None))

        await FarmCog._notificar_aprovacao(
            cog, guild, "1234", membro, antecipada=True
        )

        membro.send.assert_awaited_once()
        kwargs = membro.send.await_args.kwargs
        self.assertEqual(len(kwargs["files"]), 1)
        self.assertIn("Aprovação Antecipada", kwargs["embed"].title)
        kwargs["files"][0].close()

    async def test_dm_assume_quando_o_envio_na_pasta_falha(self):
        membro = _fake_membro()
        guild = _fake_guild(membro)
        pasta = SimpleNamespace(
            id=777, send=AsyncMock(side_effect=discord.Forbidden)
        )
        cog = SimpleNamespace(_resolver_pasta_privada=AsyncMock(return_value=pasta))

        await FarmCog._notificar_aprovacao(
            cog, guild, "1234", membro, antecipada=False
        )

        pasta.send.assert_awaited_once()
        membro.send.assert_awaited_once()
        for chamada in (pasta.send, membro.send):
            chamada.await_args.kwargs["files"][0].close()


if __name__ == "__main__":
    unittest.main()
