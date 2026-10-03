import unittest
from types import SimpleNamespace

from cogs.set_views import _get_flanelinha_role, _get_member_role, _get_pedir_set_role


class FakeGuild:
    def __init__(self, roles):
        self.roles = roles

    def get_role(self, role_id):
        return next((role for role in self.roles if role.id == role_id), None)


class SetApprovalRoleTests(unittest.TestCase):
    def test_usa_membro_configurado_no_banco(self):
        role = SimpleNamespace(id=123, name="Cargo Custom")
        guild = FakeGuild([role])
        cfg = {"member_role_id": "123"}

        self.assertIs(_get_member_role(guild, cfg), role)

    def test_fallback_por_nome_membro(self):
        role = SimpleNamespace(id=456, name="| Membro")
        guild = FakeGuild([role])

        self.assertIs(_get_member_role(guild, None), role)

    def test_membro_inexistente(self):
        guild = FakeGuild([SimpleNamespace(id=1, name="| Pedir Set")])

        self.assertIsNone(_get_member_role(guild, None))

    def test_usa_flanelinha_configurado_no_banco(self):
        role = SimpleNamespace(id=123, name="Cargo Custom")
        guild = FakeGuild([role])
        cfg = {"flanelinha_role_id": "123"}

        self.assertIs(_get_flanelinha_role(guild, cfg), role)

    def test_fallback_por_nome_flanelinha(self):
        role = SimpleNamespace(id=456, name="Flanelinha")
        guild = FakeGuild([role])

        self.assertIs(_get_flanelinha_role(guild, None), role)

    def test_pedir_set_por_nome(self):
        role = SimpleNamespace(id=789, name="| Pedir Set")
        guild = FakeGuild([role])

        self.assertIs(_get_pedir_set_role(guild), role)


if __name__ == "__main__":
    unittest.main()
