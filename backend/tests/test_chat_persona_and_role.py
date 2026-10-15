"""Test suite for LLM persona, user name addressing, and role-based response rules."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.llm_analysis import OUTPUT_RULES, get_output_rules, get_persona


class ChatPersonaAndRoleTests(unittest.TestCase):
    def test_default_persona(self):
        persona = get_persona()
        self.assertIn("Persona adın Scalper", persona)
        self.assertIn("UZMAN TRADER", persona)
        self.assertIn("KESİNLİKLE yazılım/kod detaylarına", persona)

    def test_persona_addresses_user_by_name(self):
        persona = get_persona({"user_name": "Ahmet", "user_role": "user"})
        self.assertIn("Kullanıcının adı 'Ahmet'", persona)
        self.assertIn("Ahmet Bey", persona)
        self.assertIn("UZMAN TRADER", persona)

    def test_non_admin_gets_expert_trader_rules(self):
        persona = get_persona({"username": "Erkan", "role": "user"})
        self.assertIn("Erkan", persona)
        self.assertIn("UZMAN TRADER - STANDART KULLANICI", persona)
        self.assertIn("KESİNLİKLE yazılım/kod detaylarına, veritabanı tablolarına", persona)
        self.assertIn("Bir trader gibi konuş", persona)
        self.assertNotIn("SİSTEM YÖNETİCİSİ / ADMIN", persona)

    def test_admin_gets_admin_rules(self):
        persona = get_persona({"username": "root", "role": "admin"})
        self.assertIn("root", persona)
        self.assertIn("SİSTEM YÖNETİCİSİ / ADMIN", persona)
        self.assertIn("yazılım mimarisi, veritabanı tabloları", persona)
        self.assertNotIn("UZMAN TRADER - STANDART KULLANICI", persona)

    def test_admin_gets_technical_analysis_format(self):
        persona = get_persona({"username": "root", "role": "admin"})
        self.assertIn("TEKNİK ANALİZ FORMATI", persona)
        self.assertIn("Gösterge tablosu", persona)
        self.assertNotIn("SIFIR TEKNİK TERİM", persona)

    def test_non_admin_keeps_plain_language_rule(self):
        for snap in (None, {"role": "user"}, {"role": "viewer"}, {"role": ""}):
            persona = get_persona(snap)
            self.assertIn("SIFIR TEKNİK TERİM", persona)
            self.assertNotIn("TEKNİK ANALİZ FORMATI", persona)

    def test_output_rules_follow_role(self):
        admin_rules = get_output_rules({"user_role": "admin"})
        self.assertIn("TEKNİK ANALİZ FORMATI", admin_rules)
        self.assertNotIn("KESİNLİKLE GÖSTERGE LİSTESİ DÖKÜMÜ YAPMA", admin_rules)
        for snap in (None, {"user_role": "user"}, {"user_role": "operator"}):
            rules = get_output_rules(snap)
            self.assertIn("KESİNLİKLE GÖSTERGE LİSTESİ DÖKÜMÜ YAPMA", rules)
            self.assertEqual(rules, OUTPUT_RULES)


if __name__ == "__main__":
    unittest.main()
