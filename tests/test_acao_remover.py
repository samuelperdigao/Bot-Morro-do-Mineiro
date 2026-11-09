import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from cogs.acao import RemoverMembroView


def _participantes(n):
    return [{"user_id": str(1000 + i), "user_name": f"Membro {i}"} for i in range(n)]


class RemoverMembroPaginadoTests(unittest.IsolatedAsyncioTestCase):
    def _select(self, view):
        return next(item for item in view.children if isinstance(item, discord.ui.Select))

    def test_poucos_inscritos_cabem_numa_pagina_sem_navegacao(self):
        view = RemoverMembroView(1, None, _participantes(5))
        self.assertEqual(len(self._select(view).options), 5)
        self.assertEqual(len(view.children), 1)

    async def test_todos_os_inscritos_ficam_acessiveis(self):
        participantes = _participantes(45)
        view = RemoverMembroView(1, None, participantes)
        vistos = []
        interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))
        for pagina in range(view._total_paginas()):
            opcoes = self._select(view).options
            self.assertLessEqual(len(opcoes), 25)
            vistos.extend(option.value for option in opcoes)
            if pagina < view._total_paginas() - 1:
                await view._next(interaction)
        self.assertEqual(vistos, [p["user_id"] for p in participantes])


if __name__ == "__main__":
    unittest.main()
