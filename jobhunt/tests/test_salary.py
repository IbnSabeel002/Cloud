import unittest

from jobhunt.salary import parse_pay


class ParsePayTests(unittest.TestCase):
    def assertRange(self, text, low, high, **extra):
        pay = parse_pay(text)
        self.assertIsNotNone(pay, f"could not parse {text!r}")
        if low is None:
            self.assertIsNone(pay.low, text)
        else:
            self.assertAlmostEqual(pay.low, low, places=1, msg=text)
        if high is None:
            self.assertIsNone(pay.high, text)
        else:
            self.assertAlmostEqual(pay.high, high, places=1, msg=text)
        for key, value in extra.items():
            self.assertEqual(getattr(pay, key), value, f"{text!r}.{key}")
        return pay

    # Real strings seen on Indeed UAE, Bayt and Glassdoor on 2026-10-05.
    def test_indeed_fresher_listing(self):
        pay = self.assertRange("AED3,500 - AED4,000 a month", 3500, 4000, currency="AED", period="month")
        self.assertEqual(pay.assumptions, ())

    def test_bayt_band(self):
        self.assertRange("AED 3,673 - AED 5,509", 3673, 5509)

    def test_glassdoor_k_suffix(self):
        self.assertRange("AED 5K - AED 11K/mo", 5000, 11000)

    def test_employer_provided_single_figure(self):
        self.assertRange("AED 10,000 (Employer provided)", 10000, 10000)

    def test_decimals(self):
        self.assertRange("Pay: AED2,000.00 - AED3,000.00 per month", 2000, 3000)

    def test_en_dash_and_no_currency(self):
        pay = self.assertRange("25,000 – 35,000/month", 25000, 35000)
        self.assertIn("currency_assumed_aed", pay.assumptions)

    def test_up_to(self):
        self.assertRange("Salary upto - 4000", None, 4000)

    def test_lower_bound_forms(self):
        self.assertRange("AED 8,000+", 8000, None)
        self.assertRange("from AED 6,000", 6000, None)

    def test_base_plus_commission_is_a_floor_not_a_cap(self):
        self.assertRange("AED 4,000 + commission", 4000, None)

    def test_other_currencies_convert_to_aed(self):
        self.assertRange("USD 4,000 per month", 4000 * 3.6725, 4000 * 3.6725, currency="USD")

    def test_yearly_to_monthly(self):
        self.assertRange("AED 120,000 per year", 10000, 10000, period="year")

    def test_large_figure_without_period_is_assumed_yearly(self):
        pay = self.assertRange("AED 120,000", 10000, 10000)
        self.assertIn("period_assumed_yearly", pay.assumptions)

    def test_hourly_and_daily(self):
        self.assertRange("AED 150 per hour", 150 * 8 * 22, 150 * 8 * 22)
        self.assertRange("AED 300 per day", 300 * 22, 300 * 22)

    def test_experience_numbers_are_not_pay(self):
        self.assertRange("3-5 years experience, AED 7,000", 7000, 7000)

    def test_package_with_many_numbers_uses_first_only(self):
        pay = parse_pay("Basic 4000 + housing 1000 + transport 500")
        self.assertEqual(pay.low, 4000)
        self.assertIsNone(pay.high)
        self.assertIn("multiple_numbers_used_first", pay.assumptions)

    def test_no_number_means_unknown(self):
        for text in (None, "", "N/A", "Competitive", "Negotiable", "Employer provided", "DOE"):
            self.assertIsNone(parse_pay(text), repr(text))

    def test_midpoint_and_ceiling(self):
        pay = parse_pay("AED 5,000 - 11,000")
        self.assertEqual(pay.midpoint, 8000)
        self.assertEqual(pay.ceiling, 11000)
        floor_only = parse_pay("AED 8,000+")
        self.assertEqual(floor_only.midpoint, 8000)
        self.assertIsNone(floor_only.ceiling)


if __name__ == "__main__":
    unittest.main()
