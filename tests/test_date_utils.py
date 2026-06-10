from datetime import datetime, timezone
import unittest

from core.date_utils import (
    format_date_br,
    format_datetime_br,
    format_week_range_br,
    normalize_date_br,
    parse_date_br,
    week_id_from_date_br,
)


class DateUtilsTests(unittest.TestCase):
    def test_normalize_date_br_accepts_valid_date(self):
        self.assertEqual(normalize_date_br("08/06/2026"), "08/06/2026")

    def test_parse_date_br_rejects_iso_format(self):
        with self.assertRaises(ValueError):
            parse_date_br("2026-06-08")

    def test_parse_date_br_rejects_missing_year(self):
        with self.assertRaises(ValueError):
            parse_date_br("08/06")

    def test_parse_date_br_rejects_impossible_date(self):
        with self.assertRaises(ValueError):
            parse_date_br("31/02/2026")

    def test_format_date_br_converts_iso_storage(self):
        self.assertEqual(format_date_br("2026-06-08"), "08/06/2026")

    def test_format_datetime_br_uses_brazil_timezone(self):
        value = datetime(2026, 6, 8, 15, 30, tzinfo=timezone.utc)
        self.assertEqual(format_datetime_br(value), "08/06/2026 12:30")

    def test_week_id_from_date_br_uses_monday(self):
        self.assertEqual(week_id_from_date_br("14/06/2026"), "2026-06-08")

    def test_format_week_range_br_uses_monday_through_sunday(self):
        self.assertEqual(
            format_week_range_br("2026-06-08"),
            "08/06/2026 a 14/06/2026",
        )


if __name__ == "__main__":
    unittest.main()
