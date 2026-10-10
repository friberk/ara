"""OpenAlex lookup and content fixtures (ARA-087); they prove behavior, not live access."""

import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class FullTextFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "fulltext_test_server", Path(__file__).with_name("server.py")
        )
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)
        cls.server = cls.module.ThreadingHTTPServer(("127.0.0.1", 0), cls.module.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def get(self, path, *, key=True):
        separator = "&" if "?" in path else "?"
        url = self.base + path + (f"{separator}api_key=fixture-key" if key else "")
        opener = urllib.request.build_opener(NoRedirect())
        try:
            return opener.open(url)
        except urllib.error.HTTPError as error:
            return error

    def test_openalex_and_semantic_cases_have_matching_dois(self):
        with urllib.request.urlopen(self.base + "/works?search=fulltext-open") as response:
            row = json.load(response)["results"][0]
        with urllib.request.urlopen(
            self.base + "/graph/v1/paper/search?query=fulltext-open"
        ) as response:
            s2 = json.load(response)["data"][0]
        self.assertEqual(row["doi"], "https://doi.org/10.5555/fulltext-open")
        self.assertEqual(s2["externalIds"]["DOI"], "10.5555/fulltext-open")

    def test_lookups_report_stored_content_by_work_or_doi(self):
        for path, work, stored in [
            ("/works/W19001?select=id,has_content", "W19001", True),
            ("/works/W19007?select=id,has_content", "W19007", False),
            ("/works/doi:10.5555/fulltext-doi?select=id,has_content", "W19002", True),
        ]:
            with self.get(path, key=False) as response:
                row = json.load(response)
            self.assertEqual(row["id"], f"https://openalex.org/{work}")
            self.assertIs(row["has_content"]["pdf"], stored)
        response = self.get("/works/doi:10.5555/fulltext-semantic", key=False)
        self.assertEqual(response.status, 404)
        response.close()

    def test_content_needs_a_key_and_redirects_to_signed_storage(self):
        response = self.get("/content/works/W19001.pdf", key=False)
        self.assertEqual(response.status, 401)
        response.close()
        response = self.get("/content/works/W19001.pdf")
        self.assertEqual(response.status, 302)
        location = urllib.parse.urlsplit(response.headers["Location"])
        response.close()
        self.assertEqual(
            location.hostname, "a452eddbbe06eb7d02f4879cee70d29c.r2.cloudflarestorage.com"
        )
        self.assertEqual(location.path, "/openalex-pdfs/fulltext-open.pdf")
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "fixture.pdf"
            source.write_bytes(b"%PDF-1.7\nfixture")
            self.module.FULLTEXT.pdf_path = source
            with self.get("/storage/openalex-pdfs/fulltext-open.pdf", key=False) as pdf:
                self.assertEqual(pdf.read(), b"%PDF-1.7\nfixture\n% fulltext-open\n")

    def test_limited_case_waits_until_granted(self):
        self.module.FULLTEXT.granted.discard("fulltext-limited")
        response = self.get("/content/works/W19003.pdf")
        self.assertEqual((response.status, response.headers["Retry-After"]), (429, "2"))
        response.close()
        request = urllib.request.Request(
            self.base + "/__fulltext_fixture/fulltext-limited/grant", data=b"{}"
        )
        with urllib.request.urlopen(request) as granted:
            self.assertTrue(json.load(granted)["granted"])
        response = self.get("/content/works/W19003.pdf")
        self.assertEqual(response.status, 302)
        response.close()

    def test_spent_allowance_missing_copy_html_and_unsafe_cases_are_distinct(self):
        spent = self.get("/content/works/W19005.pdf")
        self.assertEqual(spent.status, 429)
        self.assertEqual(spent.headers["X-RateLimit-Remaining"], "0")
        self.assertEqual(spent.headers["X-RateLimit-Reset"], "3600")
        spent.close()
        missing = self.get("/content/works/W19007.pdf")
        self.assertEqual(missing.status, 404)
        missing.close()
        unsafe = self.get("/content/works/W19006.pdf")
        self.assertEqual(urllib.parse.urlsplit(unsafe.headers["Location"]).hostname, "arxiv.org")
        unsafe.close()
        with self.get("/storage/openalex-pdfs/fulltext-html.pdf", key=False) as html:
            self.assertIn(b"<html>", html.read())

    def test_recovery_case_has_distinct_identity(self):
        with urllib.request.urlopen(self.base + "/works?search=fulltext-recovery") as response:
            row = json.load(response)["results"][0]
        self.assertEqual(row["doi"], "https://doi.org/10.5555/fulltext-recovery")

    def test_fixture_can_hold_and_release_a_download(self):
        request = urllib.request.Request(
            self.base + "/__fulltext_fixture/fulltext-open/hold", data=b"{}"
        )
        urllib.request.urlopen(request).close()
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "fixture.pdf"
            source.write_bytes(b"%PDF-1.7\nfixture")
            self.module.FULLTEXT.pdf_path = source
            finished = threading.Event()
            result = []

            def fetch():
                with self.get("/storage/openalex-pdfs/fulltext-open.pdf", key=False) as pdf:
                    result.append(pdf.read())
                finished.set()

            thread = threading.Thread(target=fetch, daemon=True)
            thread.start()
            try:
                self.assertFalse(finished.wait(0.2))
            finally:
                release = urllib.request.Request(
                    self.base + "/__fulltext_fixture/fulltext-open/release", data=b"{}"
                )
                urllib.request.urlopen(release).close()
                thread.join(3)
            self.assertTrue(finished.is_set())
            self.assertEqual(result, [b"%PDF-1.7\nfixture\n% fulltext-open\n"])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args):
        return None
