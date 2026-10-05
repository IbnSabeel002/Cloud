import unittest
from datetime import date

from jobhunt.dates import age_days, parse_posted

TODAY = date(2026, 10, 5)


class ParsePostedTests(unittest.TestCase):
    def day(self, raw):
        p = parse_posted(raw, TODAY)
        self.assertIsNotNone(p, f"could not parse {raw!r}")
        return p

    def test_indeed_connector_format(self):
        p = self.day("Posted on: October 02, 2026")
        self.assertEqual(p.day, date(2026, 10, 2))
        self.assertTrue(p.exact)

    def test_month_name_variants(self):
        self.assertEqual(self.day("October 02, 2026").day, date(2026, 10, 2))
        self.assertEqual(self.day("Oct 2, 2026").day, date(2026, 10, 2))
        self.assertEqual(self.day("2 Oct 2026").day, date(2026, 10, 2))
        self.assertEqual(self.day("2nd October 2026").day, date(2026, 10, 2))
        self.assertEqual(self.day("Sept 5, 2026").day, date(2026, 9, 5))

    def test_iso(self):
        self.assertEqual(self.day("2026-10-02").day, date(2026, 10, 2))
        self.assertEqual(self.day("2026-10-02T08:30:00Z").day, date(2026, 10, 2))

    def test_relative_days(self):
        p = self.day("16 days ago")
        self.assertEqual(p.day, date(2026, 9, 19))
        self.assertTrue(p.exact)
        self.assertEqual(self.day("1 day ago").day, date(2026, 10, 4))

    def test_lower_bound_is_not_exact(self):
        p = self.day("30+ days ago")
        self.assertEqual(p.day, date(2026, 9, 5))
        self.assertFalse(p.exact)

    def test_relative_units(self):
        self.assertEqual(self.day("3 hours ago").day, TODAY)
        self.assertEqual(self.day("2 weeks ago").day, date(2026, 9, 21))
        self.assertEqual(self.day("1 month ago").day, date(2026, 9, 5))

    def test_words(self):
        for word in ("Today", "Just posted", "just now", "New", "Posted today"):
            self.assertEqual(self.day(word).day, TODAY, word)
        self.assertEqual(self.day("Yesterday").day, date(2026, 10, 4))

    def test_gulftalent_day_month_without_year(self):
        p = self.day("21 Sep")
        self.assertEqual(p.day, date(2026, 9, 21))
        self.assertFalse(p.exact)
        self.assertEqual(self.day("9 Jul").day, date(2026, 7, 9))

    def test_month_day_without_year(self):
        self.assertEqual(self.day("Sep 21").day, date(2026, 9, 21))

    def test_future_date_without_year_rolls_back_a_year(self):
        # "30 Dec" seen on 5 Oct cannot be this year's December.
        self.assertEqual(self.day("30 Dec").day, date(2025, 12, 30))

    def test_unparseable_returns_none(self):
        for bad in (None, "", "   ", "sometime soon", "Feb 30, 2026", "13/45/2026"):
            self.assertIsNone(parse_posted(bad, TODAY), repr(bad))


class AgeDaysTests(unittest.TestCase):
    def test_age(self):
        self.assertEqual(age_days(parse_posted("October 02, 2026", TODAY), TODAY), 3)
        self.assertEqual(age_days(parse_posted("Today", TODAY), TODAY), 0)

    def test_none(self):
        self.assertIsNone(age_days(None, TODAY))

    def test_future_posting_is_clamped_to_zero(self):
        self.assertEqual(age_days(parse_posted("2026-10-09", TODAY), TODAY), 0)


if __name__ == "__main__":
    unittest.main()
