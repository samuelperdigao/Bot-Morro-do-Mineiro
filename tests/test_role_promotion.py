import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.role_promotion import promote_role


class FakeRole:
    def __init__(self, role_id, position, *, default=False):
        self.id = role_id
        self.position = position
        self._default = default

    def is_default(self):
        return self._default

    def __hash__(self):
        return hash(self.id)

    def __le__(self, other):
        return self.position <= other.position


class RolePromotionTests(unittest.IsolatedAsyncioTestCase):
    async def test_troca_flanelinha_por_membro_preservando_outros_cargos(self):
        everyone = FakeRole(1, 0, default=True)
        flanelinha = FakeRole(2, 3)
        membro = FakeRole(3, 4)
        outro = FakeRole(4, 2)
        bot_role = FakeRole(5, 10)
        bot_member = SimpleNamespace(
            guild_permissions=SimpleNamespace(manage_roles=True),
            top_role=bot_role,
        )
        guild = SimpleNamespace(me=bot_member)
        member = SimpleNamespace(
            roles=[everyone, outro, flanelinha],
            guild=guild,
            edit=AsyncMock(),
        )

        result = await promote_role(
            member,
            flanelinha,
            membro,
            reason="test",
        )

        self.assertTrue(result.promoted)
        member.edit.assert_awaited_once_with(
            roles=[outro, membro],
            reason="test",
        )

    async def test_nao_altera_quem_nao_tem_flanelinha(self):
        membro = FakeRole(3, 4)
        flanelinha = FakeRole(2, 3)
        member = SimpleNamespace(roles=[membro], edit=AsyncMock())

        result = await promote_role(member, flanelinha, membro, reason="test")

        self.assertFalse(result.promoted)
        self.assertEqual(result.reason, "source_role_missing")
        member.edit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
