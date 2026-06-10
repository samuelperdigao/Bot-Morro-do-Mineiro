import unittest

from cogs.paineis import RANKING_WEEKS_PER_PAGE, RankingHistoryView
from services.db_service import current_week_id


class RankingHistoryViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_page_starts_with_current_week(self):
        view = RankingHistoryView(None, "guild-test")
        select = view.children[0]

        self.assertEqual(len(select.options), RANKING_WEEKS_PER_PAGE)
        self.assertEqual(select.options[0].value, current_week_id())
        self.assertTrue(view.children[2].disabled)
        view.stop()

    async def test_older_page_enables_newer_navigation(self):
        view = RankingHistoryView(None, "guild-test", page=1)
        select = view.children[0]

        self.assertNotEqual(select.options[0].value, current_week_id())
        self.assertFalse(view.children[2].disabled)
        view.stop()


if __name__ == "__main__":
    unittest.main()
