import unittest

from jobhunt.normalize import job_id, job_key, norm_city, norm_company, norm_title


class NormalizeTests(unittest.TestCase):
    def test_company_suffixes_are_stripped(self):
        cases = {
            "Azya Consulting FZ LLE": "azya consulting",
            "MM INTERNATIONAL TRADING FZCO": "mm international trading",
            "CREDITCARE CREDIT MANAGEMENT LLC": "creditcare credit management",
            "Jaxtox Real Estate L.L.C": "jaxtox real estate",
            "BlueFin Real Estate L.L.C": "bluefin real estate",
            "Huda Beauty": "huda beauty",
            "Al-Futtaim": "al-futtaim",
        }
        for raw, expected in cases.items():
            self.assertEqual(norm_company(raw), expected, raw)

    def test_company_ampersand_and_punctuation(self):
        self.assertEqual(norm_company("Trade & Co."), "trade and")

    def test_title_drops_location_and_parentheticals(self):
        cases = {
            "Senior Social Media Manager (Global) - Dubai": "senior social media manager",
            "Social Media & Digital Content Specialist (Onsite - Dubai)": "social media and digital content specialist",
            "Social Media Manager | Dubai": "social media manager",
            "Creative AI Specialist": "creative ai specialist",
        }
        for raw, expected in cases.items():
            self.assertEqual(norm_title(raw), expected, raw)

    def test_city(self):
        self.assertEqual(norm_city("Dubai Healthcare City"), "dubai")
        self.assertEqual(norm_city("Abu Dhabi, UAE"), "abu dhabi")
        self.assertEqual(norm_city(""), "dubai")
        self.assertEqual(norm_city(None), "dubai")

    def test_same_job_from_two_boards_has_one_key(self):
        indeed = job_key("Land Sterling Property Consultants", "Marketing Manager - Brokerage & Group Support", "Dubai")
        bayt = job_key("Land Sterling Property Consultants L.L.C", "Marketing Manager - Brokerage & Group Support (Dubai)", "Dubai, UAE")
        self.assertEqual(indeed, bayt)

    def test_different_jobs_have_different_keys(self):
        a = job_key("Acme", "Social Media Manager", "Dubai")
        b = job_key("Acme", "Social Media Specialist", "Dubai")
        c = job_key("Acme", "Social Media Manager", "Abu Dhabi")
        self.assertEqual(len({a, b, c}), 3)

    def test_job_id_is_stable_and_short(self):
        key = job_key("Acme", "Social Media Manager", "Dubai")
        self.assertEqual(job_id(key), job_id(key))
        self.assertRegex(job_id(key), r"^j_[0-9a-f]{10}$")


if __name__ == "__main__":
    unittest.main()
