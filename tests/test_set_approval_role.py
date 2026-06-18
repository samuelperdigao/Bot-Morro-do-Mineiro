import unittest
from types import SimpleNamespace

from cogs.set_views import _get_flanelinha_role


class FakeGuild:
    def __init__(self, roles):
        self.roles = roles

    def get_role(self, role_id):
        return next((role for role in self.roles if role.id == role_id), None)


class SetApprovalRoleTests(unittest.TestCase):
    def test_usa_flanelinha_configurado_no_banco(self):
        role = SimpleNamespace(id=123, name="Cargo Custom")
        guild = FakeGuild([role])
        cfg = {"flanelinha_role_id": "123"}

        self.assertIs(_get_flanelinha_role(guild, cfg), role)

    def test_fallback_por_nome_flanelinha(self):
        role = SimpleNamespace(id=456, name="Flanelinha")
        guild = FakeGuild([role])

        self.assertIs(_get_flanelinha_role(guild, None), role)


if __name__ == "__main__":
    unittest.main()
