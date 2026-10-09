"""Public HTTP fixtures cover access transitions without pretending to prove entitlements."""

import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
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

    def test_openalex_and_semantic_cases_have_matching_dois_and_access_fields(self):
        with urllib.request.urlopen(self.base + "/works?search=fulltext-open") as response:
            row = json.load(response)["results"][0]
        with urllib.request.urlopen(
            self.base + "/graph/v1/paper/search?query=fulltext-open"
        ) as response:
            s2 = json.load(response)["data"][0]
        self.assertEqual(row["doi"], "https://doi.org/10.5555/fulltext-open")
        self.assertTrue(s2.get("isOpenAccess"))
        self.assertTrue(s2["openAccessPdf"]["url"].endswith("fulltext-open"))

    def test_semantic_no_pdf_has_exact_doi_alternative(self):
        with urllib.request.urlopen(self.base + "/graph/v1/paper/s2-fulltext-doi") as response:
            row = json.load(response)
        self.assertIsNone(row["openAccessPdf"])
        with urllib.request.urlopen(
            self.base + "/works?filter=doi:https://doi.org/10.5555/fulltext-doi"
        ) as response:
            alternate = json.load(response)["results"][0]
        self.assertTrue(alternate["best_oa_location"]["pdf_url"].endswith("fulltext-doi"))

    def test_denied_case_can_be_granted_and_returns_original_pdf(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "fixture.pdf"
            source.write_bytes(b"%PDF-1.7\nfixture")
            self.module.FULLTEXT.pdf_path = source
            self.module.FULLTEXT.granted.discard("fulltext-denied")
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.base + "/fulltext/pdf/fulltext-denied")
            self.assertEqual(error.exception.code, 403)
            request = urllib.request.Request(
                self.base + "/__fulltext_fixture/fulltext-denied/grant",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request) as response:
                self.assertTrue(json.load(response)["granted"])
            with urllib.request.urlopen(self.base + "/fulltext/pdf/fulltext-denied") as response:
                self.assertEqual(response.read(), b"%PDF-1.7\nfixture\n% fulltext-denied\n")

    def test_html_and_rate_limit_are_distinct(self):
        with urllib.request.urlopen(self.base + "/fulltext/pdf/fulltext-html") as response:
            self.assertIn(b"<html>", response.read())
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(self.base + "/fulltext/pdf/fulltext-rate")
        self.assertEqual(error.exception.code, 429)

    def test_recovery_case_has_distinct_identity(self):
        with urllib.request.urlopen(self.base + "/works?search=fulltext-recovery") as response:
            row = json.load(response)["results"][0]
        self.assertEqual(row["doi"], "https://doi.org/10.5555/fulltext-recovery")

    def test_direct_semantic_copy_has_no_openalex_alternative(self):
        with urllib.request.urlopen(self.base + "/graph/v1/paper/s2-fulltext-semantic") as response:
            row = json.load(response)
        self.assertIsNotNone(row["openAccessPdf"])
        self.assertTrue(row["openAccessPdf"]["url"].endswith("fulltext-semantic"))
        with urllib.request.urlopen(
            self.base + "/works?filter=doi:https://doi.org/10.5555/fulltext-semantic"
        ) as response:
            alternate = json.load(response)
        self.assertEqual(alternate["results"], [])

    def test_fixture_can_hold_and_release_a_download(self):
        request = urllib.request.Request(
            self.base + "/__fulltext_fixture/fulltext-open/hold", data=b"{}"
        )
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as error:
            response = error
        self.assertEqual(response.status, 200)
        response.close()
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "fixture.pdf"
            source.write_bytes(b"%PDF-1.7\nfixture")
            self.module.FULLTEXT.pdf_path = source
            finished = threading.Event()
            result = []

            def fetch():
                with urllib.request.urlopen(self.base + "/fulltext/pdf/fulltext-open") as pdf:
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

    def test_unsafe_redirect_is_a_fixture_not_a_live_request(self):
        opener = urllib.request.build_opener(NoRedirect())
        with self.assertRaises(urllib.error.HTTPError) as error:
            opener.open(self.base + "/fulltext/pdf/fulltext-unsafe")
        self.assertEqual(error.exception.code, 302)
        self.assertEqual(error.exception.headers["Location"], "http://127.0.0.1/private")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args):
        return None
