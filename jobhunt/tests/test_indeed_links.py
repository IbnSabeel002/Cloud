import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from jobhunt.cli import main
from jobhunt.indeed_links import job_links, links_by_page, pages_in

FIXTURE = Path(__file__).parent / "fixtures" / "indeed_page_links.json"
PAGE_LINKS = json.loads(FIXTURE.read_text())["results"][0]["links"]
EXPECTED = [
    "https://ae.indeed.com/viewjob?jk=43c9bed78d63bb94",
    "https://ae.indeed.com/viewjob?jk=cc8b0f1c66064257",
    "https://ae.indeed.com/viewjob?jk=a99402720521a673",
    "https://ae.indeed.com/viewjob?jk=51bdd435c82ebaef",
    "https://ae.indeed.com/viewjob?jk=ed99e8146d6d9964",
]


class JobLinkTests(unittest.TestCase):
    def test_the_real_page_gives_one_clean_link_per_card_in_page_order(self):
        self.assertEqual(job_links(PAGE_LINKS), EXPECTED)

    def test_a_job_listed_twice_is_listed_once_at_its_first_place(self):
        self.assertEqual(job_links(PAGE_LINKS).count("https://ae.indeed.com/viewjob?jk=a99402720521a673"), 1)

    def test_the_template_link_indeed_leaves_in_the_page_is_not_a_job(self):
        self.assertNotIn("https://ae.indeed.com/viewjob?jk=abcdef0123456789", job_links(PAGE_LINKS))

    def test_salary_pages_and_encoded_apply_links_are_not_job_links(self):
        only_noise = [l for l in PAGE_LINKS if "fromjk=" in l or "smartapply" in l or "/q-" in l or "/cmp/" in l]
        self.assertTrue(only_noise)
        self.assertEqual(job_links(only_noise), [])

    def test_the_search_page_itself_is_not_a_job_link(self):
        self.assertEqual(job_links(["https://ae.indeed.com/jobs?q=ai&l=Dubai&fromage=3&sort=date"]), [])

    def test_the_result_has_no_tracking_and_keeps_the_host(self):
        for link in job_links(PAGE_LINKS):
            self.assertNotIn("&", link)
            self.assertTrue(link.startswith("https://ae.indeed.com/viewjob?jk="))
        self.assertEqual(job_links(["https://uk.indeed.com/rc/clk?jk=0123456789abcdef&bb=x"]),
                         ["https://uk.indeed.com/viewjob?jk=0123456789abcdef"])

    def test_an_id_must_be_sixteen_hex_characters_exactly(self):
        self.assertEqual(job_links(["https://ae.indeed.com/rc/clk?jk=abc&bb=x"]), [])
        self.assertEqual(job_links(["https://ae.indeed.com/rc/clk?jk=0123456789abcdef0&bb=x"]), [])

    def test_a_from_jk_parameter_is_not_the_jobs_own_id(self):
        # Salary pages carry the id of the job they were opened from; that is a pointer, not this job.
        self.assertEqual(job_links(["https://ae.indeed.com/viewjob?fromjk=0123456789abcdef"]), [])
        self.assertEqual(job_links(["https://ae.indeed.com/rc/clk?from=serp&fromjk=0123456789abcdef&bb=x"]), [])

    def test_an_id_that_is_not_the_first_parameter_is_still_found(self):
        self.assertEqual(job_links(["https://ae.indeed.com/viewjob?from=serp&jk=0123456789abcdef"]),
                         ["https://ae.indeed.com/viewjob?jk=0123456789abcdef"])

    def test_empty_and_none(self):
        self.assertEqual(job_links([]), [])
        self.assertEqual(job_links(None), [])


class FileTests(unittest.TestCase):
    def test_reads_a_fetch_content_file(self):
        self.assertEqual(links_by_page(FIXTURE)[0]["job_links"], EXPECTED)

    def test_reads_a_bare_list_of_links_and_text_around_the_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "links.json"
            path.write_text("saved to file:\n" + json.dumps(PAGE_LINKS))
            self.assertEqual(links_by_page(path)[0]["job_links"], EXPECTED)

    def test_a_file_that_is_not_a_fetch_result_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            path.write_text(json.dumps({"hello": 1}))
            with self.assertRaises(ValueError):
                pages_in(path)
            path.write_text("no json here")
            with self.assertRaises(ValueError):
                pages_in(path)


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_prints_the_links_per_page(self):
        code, out, _ = self.run_cli("indeed-links", "--page", str(FIXTURE))
        self.assertEqual(code, 0)
        pages = json.loads(out)
        self.assertEqual(pages[0]["job_links"], EXPECTED)
        self.assertIn("jobs?q=Generative", pages[0]["page"])

    def test_a_missing_or_unreadable_file_exits_2(self):
        code, _, err = self.run_cli("indeed-links", "--page", "/no/such/file.json")
        self.assertEqual(code, 2)
        self.assertIn("error", err)


if __name__ == "__main__":
    unittest.main()
