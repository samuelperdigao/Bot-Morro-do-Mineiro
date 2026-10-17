import unittest
from pathlib import Path

from core.extensions import COG_EXTENSIONS


class LegacyDashboardTests(unittest.TestCase):
    def test_dashboard_code_is_preserved_but_not_loaded(self):
        self.assertNotIn("cogs.dashboard", COG_EXTENSIONS)
        self.assertTrue(Path("cogs/dashboard.py").is_file())


if __name__ == "__main__":
    unittest.main()
