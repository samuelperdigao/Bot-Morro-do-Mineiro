import unittest
from types import SimpleNamespace

from cogs.hierarquia import (
    HIERARQUIA_CARGOS,
    _cargos_permitidos,
    _motivo_bloqueio_alvo,
    _nivel_hierarquia,
)

OWNER_ID = 1


def _membro(member_id: int, *cargos: str, bot: bool = False):
    guild = SimpleNamespace(owner_id=OWNER_ID)
    roles = [SimpleNamespace(name=nome, id=1000 + i) for i, nome in enumerate(cargos)]
    return SimpleNamespace(id=member_id, roles=roles, guild=guild, bot=bot)


class HierarquiaPermissaoTests(unittest.TestCase):
    def test_gerente_geral_nao_pode_atribuir_cargos_iguais_ou_acima(self):
        executor = _membro(10, "| Gerente Geral")
        permitidos = _cargos_permitidos(executor)
        self.assertNotIn("| Gerente Geral", permitidos)
        self.assertNotIn("| 02", permitidos)
        self.assertNotIn("| 01 Dono", permitidos)
        self.assertIn("| Gerente de Farm", permitidos)
        self.assertIn("| Membro", permitidos)

    def test_cargo_03_nao_existe_mais(self):
        self.assertNotIn("| 03", HIERARQUIA_CARGOS)

    def test_dono_do_servidor_pode_atribuir_todos(self):
        dono = _membro(OWNER_ID)
        self.assertEqual(_cargos_permitidos(dono), HIERARQUIA_CARGOS)

    def test_nao_altera_cargo_igual_ou_superior(self):
        executor = _membro(10, "| Gerente Geral")
        self.assertIsNotNone(_motivo_bloqueio_alvo(executor, _membro(11, "| Gerente Geral")))
        self.assertIsNotNone(_motivo_bloqueio_alvo(executor, _membro(12, "| 01 Dono")))
        self.assertIsNone(_motivo_bloqueio_alvo(executor, _membro(13, "| Membro")))

    def test_bloqueia_si_mesmo_bot_e_dono(self):
        executor = _membro(10, "| 02")
        self.assertIsNotNone(_motivo_bloqueio_alvo(executor, executor))
        self.assertIsNotNone(_motivo_bloqueio_alvo(executor, _membro(20, bot=True)))
        self.assertIsNotNone(_motivo_bloqueio_alvo(executor, _membro(OWNER_ID)))

    def test_nivel_usa_o_cargo_mais_alto(self):
        membro = _membro(30, "| Membro", "| Gerente Geral")
        self.assertEqual(_nivel_hierarquia(membro), HIERARQUIA_CARGOS.index("| Gerente Geral"))
        self.assertEqual(_nivel_hierarquia(_membro(31)), -1)


if __name__ == "__main__":
    unittest.main()
