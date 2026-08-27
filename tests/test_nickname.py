import unittest
from types import SimpleNamespace

from core.nickname import (
    NICK_MAX,
    TAG_GERENTE,
    TAG_LIDER,
    TAG_MEMBRO,
    TAG_VICE,
    build_nick,
    build_nick_from_parts,
    desired_nick,
    strip_tag,
    tag_for_member,
)


def fake_member(*role_names, nick=None, display_name=None, role_ids=None):
    ids = role_ids or list(range(100, 100 + len(role_names)))
    roles = [
        SimpleNamespace(id=role_id, name=name)
        for role_id, name in zip(ids, role_names)
    ]
    return SimpleNamespace(
        roles=roles,
        nick=nick,
        display_name=display_name or nick or "Fulano",
    )


class TagForMemberTests(unittest.TestCase):
    def test_dono_vence_os_demais_cargos(self):
        member = fake_member("| Membro", "| Gerente de Farm", "| 02", "| 01 Dono")
        self.assertEqual(tag_for_member(member), TAG_LIDER)

    def test_vice_vence_gerente(self):
        member = fake_member("| Gerente Geral", "| 02")
        self.assertEqual(tag_for_member(member), TAG_VICE)

    def test_gerente_vence_membro(self):
        member = fake_member("| Membro", "| Gerente Geral")
        self.assertEqual(tag_for_member(member), TAG_GERENTE)

    def test_gerente_detectado_por_prefixo(self):
        for nome in ("| Gerente de Produtos", "| Gerente de Ação", "| Gerente de Recrutamento"):
            with self.subTest(nome=nome):
                self.assertEqual(tag_for_member(fake_member(nome)), TAG_GERENTE)

    def test_membro_simples(self):
        self.assertEqual(tag_for_member(fake_member("| Membro")), TAG_MEMBRO)

    def test_cargos_sem_tag(self):
        for nome in ("| 03", "| Flanelinha", "| Pedir Set"):
            with self.subTest(nome=nome):
                self.assertIsNone(tag_for_member(fake_member(nome)))

    def test_sem_cargo_algum(self):
        self.assertIsNone(tag_for_member(fake_member()))

    def test_member_role_id_do_banco_reforca_membro(self):
        member = fake_member("Cargo Renomeado", role_ids=[777])
        self.assertIsNone(tag_for_member(member))
        self.assertEqual(tag_for_member(member, member_role_id=777), TAG_MEMBRO)
        self.assertEqual(tag_for_member(member, member_role_id="777"), TAG_MEMBRO)

    def test_member_role_id_invalido_e_ignorado(self):
        member = fake_member("Cargo Renomeado", role_ids=[777])
        self.assertIsNone(tag_for_member(member, member_role_id="abc"))


class StripTagTests(unittest.TestCase):
    def test_remove_tag_existente(self):
        self.assertEqual(strip_tag("[GRT] Adrian | 21751"), "Adrian | 21751")

    def test_idempotente(self):
        limpo = strip_tag("[GRT] Adrian | 21751")
        self.assertEqual(strip_tag(limpo), limpo)

    def test_nao_acumula_tags_ao_trocar(self):
        atual = "[GRT] Adrian | 21751"
        self.assertEqual(build_nick(strip_tag(atual), TAG_MEMBRO), "[MBR] Adrian | 21751")

    def test_remove_tags_acumuladas(self):
        self.assertEqual(strip_tag("[MBR] [GRT] Adrian | 21751"), "Adrian | 21751")

    def test_sem_tag_mantem_nome(self):
        self.assertEqual(strip_tag("Adrian | 21751"), "Adrian | 21751")

    def test_none_vira_string_vazia(self):
        self.assertEqual(strip_tag(None), "")


class BuildNickTests(unittest.TestCase):
    def test_monta_com_tag(self):
        self.assertEqual(build_nick("Mineiro | 6627", TAG_LIDER), "[LIDER] Mineiro | 6627")

    def test_sem_tag_devolve_base(self):
        self.assertEqual(build_nick("Mineiro | 6627", None), "Mineiro | 6627")

    def test_trunca_apenas_o_nome_preservando_tag_e_id(self):
        nick = build_nick("Nome Muito Comprido De Verdade | 41468", TAG_GERENTE)
        self.assertLessEqual(len(nick), NICK_MAX)
        self.assertTrue(nick.startswith(f"{TAG_GERENTE} "))
        self.assertTrue(nick.endswith(" | 41468"))

    def test_from_parts(self):
        self.assertEqual(
            build_nick_from_parts("Duduks Pires", "41468", TAG_MEMBRO),
            "[MBR] Duduks Pires | 41468",
        )

    def test_from_parts_sem_id(self):
        self.assertEqual(build_nick_from_parts("Duduks Pires", "", TAG_MEMBRO), "[MBR] Duduks Pires")

    def test_from_parts_trunca_no_limite(self):
        nick = build_nick_from_parts("Nome Muito Comprido De Verdade", "41468", TAG_MEMBRO)
        self.assertLessEqual(len(nick), NICK_MAX)
        self.assertTrue(nick.endswith(" | 41468"))


class DesiredNickTests(unittest.TestCase):
    def test_usa_nick_atual_sem_a_tag_antiga(self):
        member = fake_member("| Membro", nick="[GRT] Adrian | 21751")
        self.assertEqual(desired_nick(member, TAG_MEMBRO), "[MBR] Adrian | 21751")

    def test_cai_para_display_name_quando_nao_ha_nick(self):
        member = fake_member("| Membro", display_name="Adrian")
        self.assertEqual(desired_nick(member, TAG_MEMBRO), "[MBR] Adrian")

    def test_sem_tag_devolve_none(self):
        member = fake_member("| 03", nick="Zé | 1")
        self.assertIsNone(desired_nick(member, tag_for_member(member)))


if __name__ == "__main__":
    unittest.main()
