import unittest
from types import SimpleNamespace

from cogs.apelidos import apelido_alvo, is_suppressed, pode_editar, suppress
from core.nickname import TAG_MEMBRO


class FakeRole:
    """Cargo com posição comparável (o guard usa me.top_role > member.top_role)."""

    def __init__(self, position, role_id=0, name=""):
        self.position = position
        self.id = role_id
        self.name = name

    def __gt__(self, other):
        return self.position > other.position

    def __le__(self, other):
        return self.position <= other.position


def fake_member(
    *role_names,
    nick=None,
    display_name=None,
    bot=False,
    member_id=10,
    owner_id=99,
    top_role=5,
    bot_top_role=10,
    manage_nicknames=True,
):
    roles = [FakeRole(1, 100 + i, name) for i, name in enumerate(role_names)]
    me = SimpleNamespace(
        top_role=FakeRole(bot_top_role),
        guild_permissions=SimpleNamespace(manage_nicknames=manage_nicknames),
    )
    return SimpleNamespace(
        id=member_id,
        bot=bot,
        guild=SimpleNamespace(id=1, owner_id=owner_id, me=me),
        roles=roles,
        nick=nick,
        display_name=display_name or nick or "Fulano",
        top_role=FakeRole(top_role),
    )


class PodeEditarTests(unittest.TestCase):
    def test_membro_comum_pode(self):
        self.assertTrue(pode_editar(fake_member("| Membro")))

    def test_bot_e_ignorado(self):
        self.assertFalse(pode_editar(fake_member("| Membro", bot=True)))

    def test_dono_da_guild_e_ignorado(self):
        self.assertFalse(pode_editar(fake_member("| 01 Dono", member_id=99, owner_id=99)))

    def test_cargo_do_bot_abaixo_do_membro(self):
        self.assertFalse(pode_editar(fake_member("| 02", top_role=20, bot_top_role=10)))

    def test_sem_permissao_de_apelidos(self):
        self.assertFalse(pode_editar(fake_member("| Membro", manage_nicknames=False)))


class ApelidoAlvoTests(unittest.TestCase):
    def test_aplica_tag_faltante(self):
        alvo = fake_member("| Membro", nick="Duduks Pires | 41468")
        self.assertEqual(apelido_alvo(alvo, None), "[MBR] Duduks Pires | 41468")

    def test_troca_tag_antiga(self):
        alvo = fake_member("| Gerente de Farm", nick="[MBR] Adrian | 21751")
        self.assertEqual(apelido_alvo(alvo, None), "[GRT] Adrian | 21751")

    def test_nada_a_fazer_quando_ja_esta_certo(self):
        alvo = fake_member("| Membro", nick=f"{TAG_MEMBRO} Adrian | 21751")
        self.assertIsNone(apelido_alvo(alvo, None))

    def test_cargo_sem_tag_nao_mexe_no_apelido(self):
        alvo = fake_member("| 03", nick="Chefe | 1")
        self.assertIsNone(apelido_alvo(alvo, None))

    def test_member_role_id_do_banco(self):
        alvo = fake_member("Cargo Renomeado", nick="Adrian | 21751")
        self.assertIsNone(apelido_alvo(alvo, None))
        self.assertEqual(apelido_alvo(alvo, 100), "[MBR] Adrian | 21751")


class SuppressTests(unittest.TestCase):
    def test_suprime_apenas_dentro_do_bloco(self):
        self.assertFalse(is_suppressed(42))
        with suppress(42):
            self.assertTrue(is_suppressed(42))
        self.assertFalse(is_suppressed(42))

    def test_libera_mesmo_com_excecao(self):
        with self.assertRaises(RuntimeError):
            with suppress(42):
                raise RuntimeError("boom")
        self.assertFalse(is_suppressed(42))


if __name__ == "__main__":
    unittest.main()
