"""The HTTP fixture is tested at its public boundary, not by inspecting its source."""

import importlib.util
import json
from pathlib import Path
import threading
import unittest
import urllib.request


class ExternalFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "fixture_server", Path(__file__).with_name("server.py")
        )
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)
        cls.server = cls.module.ThreadingHTTPServer(
            ("127.0.0.1", 0), cls.module.Handler
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_providers_return_matching_identifiers_and_nullable_metadata(self):
        with urllib.request.urlopen(
            self.base + "/graph/v1/paper/search?query=research"
        ) as response:
            semantic = json.load(response)["data"][0]
        with urllib.request.urlopen(self.base + "/works?search=research") as response:
            openalex = json.load(response)["results"][0]
        self.assertEqual(semantic["externalIds"]["DOI"], "10.5555/cs593.fixture")
        self.assertEqual(openalex["doi"], "https://doi.org/10.5555/cs593.fixture")
        self.assertEqual(openalex["title"], "Traceable Research Systems")

    def test_responses_stream_emits_incremental_output_and_completion(self):
        body = json.dumps(
            {
                "model": "gpt-5.6-luna",
                "input": "What dataset is used? [source:11111111-1111-4111-8111-111111111111]",
                "stream": True,
            }
        ).encode()
        request = urllib.request.Request(
            self.base + "/v1/responses",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            stream = response.read().decode()
        self.assertIn("response.created", stream)
        self.assertGreater(stream.count("response.output_text.delta"), 1)
        self.assertIn("response.completed", stream)
        self.assertIn("11111111-1111-4111-8111-111111111111", stream)

    def test_structured_metadata_matches_pdf_fixture(self):
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "authors": {"type": "array", "items": {"type": "string"}},
                "year": {"type": "integer"},
                "abstract": {"type": "string"},
            },
            "required": ["title", "authors", "year", "abstract"],
        }
        body = json.dumps(
            {
                "model": "gpt-5.6-luna",
                "input": "Extract metadata",
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "metadata",
                        "schema": schema,
                    }
                },
            }
        ).encode()
        request = urllib.request.Request(
            self.base + "/v1/responses",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            result = json.load(response)
        metadata = json.loads(result["output"][0]["content"][0]["text"])
        self.assertEqual(metadata["year"], 2024)
        self.assertEqual(metadata["authors"], ["Ada Researcher"])


if __name__ == "__main__":
    unittest.main()
