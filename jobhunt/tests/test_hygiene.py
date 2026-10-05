"""Guards for the rule that this public repo holds code, never personal data.

The identifying words are stored as SHA-256 hashes so this test does not itself
disclose what it protects.
"""

import hashlib
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
TEXT_SUFFIXES = {".py", ".md", ".json", ".csv", ".txt", ".toml", ".yml", ".yaml", ".html", ".cfg", ".sh", ""}

# SHA-256 of lowercase words and two-word phrases taken from the resume (name, employers, schools).
DENIED_HASHES = {
    "f73ca3c629cb914881fa32dd679f97ce63c1b5ece56304465bcdb3a37d62e918",
    "863498dfa3f35f634f532b3cab89b0f8b6baaf9a2a94722c52ca2ef44377efc2",
    "cd2caff46d2cedb309a3407ac0911b521689269a64b69ab8300ddbeea992476b",
    "f9ec50fe2970ee2796b4a6bc25bda683e45dc871ab3815b3492668668866d382",
    "65cde4fe509319ae96ea1129c0c165af3b5901cce64c645f8d2e49a280d1d98c",
    "d99038a0cb45543b2404ba2ca31939989ec83a525db475b4dab87bb530d56838",
    "148742deb6a8fc7543ea2a2e1f1f0f704934dd27ae804f93b157c43cd2dcbd57",
    "b371c27b8a3ab3e0d25cfd57beb362243653a40bd071381558d48bf4e0d2547f",
}
ALLOWED_EMAILS = {"a@gmail.com", "hr.recruit@gmail.com"}  # fake addresses used to test the free-mail rule
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"\+\s?971|\b05\d[\s-]?\d{3}[\s-]?\d{4}\b|\b00971")


def repo_files():
    for path in REPO_ROOT.rglob("*"):
        if path.is_file() and not (set(path.parts) & SKIP_DIRS) and path.suffix.lower() in TEXT_SUFFIXES:
            if path.resolve() != SELF:
                yield path


def words(text):
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    yield from tokens
    for a, b in zip(tokens, tokens[1:]):
        yield f"{a} {b}"


class HygieneTests(unittest.TestCase):
    def read(self, path):
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ""

    def test_there_are_files_to_scan(self):
        self.assertGreater(len(list(repo_files())), 10)

    def test_no_identifying_words(self):
        hits = []
        for path in repo_files():
            for token in set(words(self.read(path))):
                if hashlib.sha256(token.encode()).hexdigest() in DENIED_HASHES:
                    hits.append(f"{path.relative_to(REPO_ROOT)}: matches a denied word")
        self.assertEqual(hits, [])

    def test_no_phone_numbers(self):
        hits = [str(p.relative_to(REPO_ROOT)) for p in repo_files() if PHONE.search(self.read(p))]
        self.assertEqual(hits, [])

    def test_no_real_email_addresses(self):
        hits = []
        for path in repo_files():
            for m in EMAIL.findall(self.read(path)):
                domain = m.rsplit("@", 1)[1].lower()
                if m.lower() in ALLOWED_EMAILS or domain.endswith((".example", ".invalid")) or domain in {"example.com", "example.org"}:
                    continue
                hits.append(f"{path.relative_to(REPO_ROOT)}: {m}")
        self.assertEqual(hits, [])

    def test_no_personal_profile_links(self):
        hits = [str(p.relative_to(REPO_ROOT)) for p in repo_files() if re.search(r"linkedin\.com/in/", self.read(p), re.I)]
        self.assertEqual(hits, [])

    def test_the_guard_itself_catches_what_it_should(self):
        # Prove each detector fires, so a silently broken regex cannot give false comfort.
        self.assertTrue(PHONE.search("call +971 50 123 4567"))
        self.assertTrue(PHONE.search("0501234567"))
        self.assertTrue(EMAIL.search("someone@company.ae"))
        self.assertIn(hashlib.sha256(b"basim").hexdigest(), DENIED_HASHES)
        self.assertIn(hashlib.sha256(b"desert whales").hexdigest(), DENIED_HASHES)
        self.assertIn(hashlib.sha256(b"pioneer triumph").hexdigest(), DENIED_HASHES)
        self.assertIn(hashlib.sha256(b"hemi").hexdigest(), DENIED_HASHES)
        self.assertIn("desert whales", set(words("Worked at Desert Whales in Dubai")))


if __name__ == "__main__":
    unittest.main()
