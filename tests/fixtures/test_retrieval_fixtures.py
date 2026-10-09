"""Retrieval fixtures are tested at their HTTP boundary (ARA-070)."""

import base64
import importlib.util
import json
from pathlib import Path
import struct
import sys
import threading
import unittest
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


class RetrievalFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load("fixture_server_retrieval", HERE / "server.py")
        cls.server = cls.module.ThreadingHTTPServer(("127.0.0.1", 0), cls.module.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def post(self, path, body):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    def test_openai_embeddings_are_deterministic_normalized_and_sized(self):
        result = self.post(
            "/v1/embeddings",
            {
                "model": "text-embedding-3-large",
                "input": ["dense retrieval of passages", "dense retrieval of passages"],
                "dimensions": 64,
                "encoding_format": "float",
            },
        )
        first, second = (item["embedding"] for item in result["data"])
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertAlmostEqual(sum(x * x for x in first), 1.0, places=5)
        self.assertEqual([item["index"] for item in result["data"]], [0, 1])
        self.assertGreater(result["usage"]["prompt_tokens"], 0)

    def test_openai_embeddings_default_dimensions_and_base64(self):
        result = self.post(
            "/v1/embeddings",
            {"model": "text-embedding-3-large", "input": "sparse lexical search"},
        )
        encoded = result["data"][0]["embedding"]
        self.assertIsInstance(encoded, str)  # the OpenAI SDK requests base64 by default
        values = struct.unpack(f"<{3072}f", base64.b64decode(encoded))
        self.assertAlmostEqual(sum(x * x for x in values), 1.0, places=4)

    def test_shared_vocabulary_is_closer_than_unrelated_text(self):
        data = self.post(
            "/v1/embeddings",
            {
                "model": "text-embedding-3-large",
                "input": [
                    "BM25 recall on the benchmark",
                    "benchmark recall of BM25 retrieval",
                    "protein folding in yeast cells",
                ],
                "dimensions": 256,
                "encoding_format": "float",
            },
        )["data"]
        query, paraphrase, unrelated = (item["embedding"] for item in data)
        self.assertGreater(cosine(query, paraphrase), cosine(query, unrelated) + 0.3)

    def test_responses_cite_short_handles_when_supplied(self):
        result = self.post(
            "/v1/responses",
            {
                "model": "gpt-5.6-luna",
                "input": [
                    {
                        "role": "user",
                        "content": "Paper passages:\n\n[S1] Results · p. 3\nBM25 reaches 0.61.\n\n"
                        "Question: What recall?",
                    }
                ],
            },
        )
        text = result["output"][0]["content"][0]["text"]
        self.assertIn("[S1]", text)
        self.assertNotIn("[source:", text)

    def test_responses_emit_insufficient_sentinel_for_marked_question(self):
        result = self.post(
            "/v1/responses",
            {
                "model": "gpt-5.6-luna",
                "input": "[S1] Methods · p. 2\nText.\n\nQuestion: NO-EVIDENCE-FIXTURE latency?",
            },
        )
        text = result["output"][0]["content"][0]["text"]
        self.assertTrue(text.startswith("[insufficient-evidence]"))

    def test_structured_arrays_honour_min_items_for_query_plans(self):
        schema = {
            "type": "object",
            "properties": {
                "standalone_question": {"type": "string"},
                "search_queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 3,
                },
                "needs_paper_evidence": {"type": "boolean"},
            },
            "required": ["standalone_question", "search_queries", "needs_paper_evidence"],
        }
        result = self.post(
            "/v1/responses",
            {
                "model": "gpt-5.6-luna",
                "input": "Plan the search",
                "text": {"format": {"type": "json_schema", "name": "plan", "schema": schema}},
            },
        )
        plan = json.loads(result["output"][0]["content"][0]["text"])
        self.assertGreaterEqual(len(plan["search_queries"]), 1)
        self.assertTrue(all(isinstance(q, str) and q for q in plan["search_queries"]))

    def decide(self, text):
        return self.post(
            "/v1/decisions",
            {
                "model": "gpt-6-luna",
                "input": text,
                "questions": [{"type": "predicate", "name": "relevance", "instructions": "Relevant?"}],
            },
        )

    def test_decisions_predicate_scores_relevant_above_irrelevant(self):
        relevant = self.decide("Query:\nBM25 recall benchmark\n\nPassage:\nBM25 recall is 0.61 on the benchmark.")
        unrelated = self.decide("Query:\nBM25 recall benchmark\n\nPassage:\nProteins fold in yeast cells.")
        for result in (relevant, unrelated):
            answer = result["answers"][0]
            self.assertEqual((answer["type"], answer["name"]), ("predicate", "relevance"))
            self.assertGreater(result["usage"]["input_tokens"], 0)
            self.assertEqual(result["usage"]["output_tokens"], 0)
        self.assertGreater(
            relevant["answers"][0]["probability"], unrelated["answers"][0]["probability"] + 0.3
        )

    def test_decisions_fixture_can_refuse_and_fail(self):
        refused = self.decide("Query:\nREFUSE-FIXTURE\n\nPassage:\nText.")
        self.assertEqual(refused["answers"][0]["type"], "refusal")
        with self.assertRaises(urllib.error.HTTPError) as failure:
            self.decide("Query:\nDECISIONS-ERROR-FIXTURE\n\nPassage:\nText.")
        self.assertEqual(failure.exception.code, 500)

    def test_ollama_embed_returns_model_dimensions_and_ignores_query_instruction(self):
        self.module.OLLAMA.installed.add("qwen3-embedding:4b-q4_K_M")
        result = self.post(
            "/api/embed",
            {
                "model": "qwen3-embedding:4b-q4_K_M",
                "input": [
                    "Instruct: Given a question about a scientific paper, retrieve passages "
                    "of the paper that answer it\nQuery: BM25 recall",
                    "BM25 recall",
                ],
            },
        )
        query, document = result["embeddings"]
        self.assertEqual(len(query), 2560)
        self.assertAlmostEqual(cosine(query, document), 1.0, places=5)
        self.assertGreater(result["prompt_eval_count"], 0)

    def test_installed_embedders_are_listed_with_pinned_digests(self):
        expected = {
            "qwen3-embedding:4b-q4_K_M": "df5bd2e3c74cd8d069d21dc038f1b359fcdc9458fce1c99bd43c9eb1518ff907",
            "qwen3-embedding:8b-q4_K_M": "64b933495768fbd3b87c20583d379728a07471e0c66733a9df87cd1901b3c44b",
        }
        self.module.OLLAMA.installed.update(expected)
        with urllib.request.urlopen(self.base + "/api/tags") as response:
            listed = {item["name"]: item["digest"] for item in json.load(response)["models"]}
        for name, digest in expected.items():
            self.assertEqual(listed[name], digest)

    def test_ollama_show_reports_embedding_capability(self):
        result = self.post("/api/show", {"model": "qwen3-embedding:8b-q4_K_M"})
        self.assertEqual(result["capabilities"], ["embedding"])
        self.assertEqual(result["model_info"]["fixture.embedding_length"], 4096)

    def test_ollama_reranker_logprobs_order_relevant_above_irrelevant(self):
        model = "fixture/qwen3-reranker-0.6b:Q8_0"
        self.module.OLLAMA.installed.add(model)

        def p_yes(document):
            prompt = (
                "<|im_start|>user\n<Instruct>: Given a question\n<Query>: BM25 recall benchmark\n"
                f"<Document>: {document}<|im_end|>\n<|im_start|>assistant\n"
            )
            result = self.post(
                "/api/generate",
                {
                    "model": model,
                    "prompt": prompt,
                    "raw": True,
                    "stream": False,
                    "logprobs": True,
                    "top_logprobs": 20,
                    "options": {"temperature": 0, "num_predict": 1},
                },
            )
            entry = result["logprobs"][0]
            tops = {item["token"]: item["logprob"] for item in entry["top_logprobs"]}
            return tops["yes"], tops["no"]

        relevant_yes, relevant_no = p_yes("BM25 reaches recall 0.61 on the benchmark")
        irrelevant_yes, irrelevant_no = p_yes("Proteins fold in yeast cells")
        self.assertGreater(relevant_yes - relevant_no, irrelevant_yes - irrelevant_no)

    def test_ollama_catalog_reranker_is_pinned_shown_and_scored(self):
        """The catalog id is mixed case and tagged; the fixture must still treat it as a reranker."""
        model = "fanyx/Qwen3-Reranker-0.6B-Q8_0:latest"
        self.assertEqual(
            sys.modules["ollama_fixture"].MODELS.get(model),
            ("fd021d86a15e539ac1b4f3bec2d1c6b15a3e158f316adb0d1325c713240103b3", 639152466),
        )
        self.module.OLLAMA.installed.add(model)
        shown = self.post("/api/show", {"model": model})
        self.assertIn("completion", shown["capabilities"])
        self.assertNotIn("thinking", shown)
        result = self.post(
            "/api/generate",
            {
                "model": model,
                "prompt": "<Query>: BM25 recall\n<Document>: BM25 recall is 0.61<|im_end|>",
                "raw": True,
                "stream": False,
                "logprobs": True,
                "top_logprobs": 20,
            },
        )
        tops = {item["token"]: item["logprob"] for item in result["logprobs"][0]["top_logprobs"]}
        self.assertGreater(tops["yes"], tops["no"])


class VectorParityTests(unittest.TestCase):
    def test_backend_and_fixture_vectors_are_identical(self):
        fixture = load("fixture_vectors", HERE / "vectors.py")
        backend = load("backend_vectors", ROOT / "src/backend/tests/support/vectors.py")
        for text in ["", "BM25 recall", "Instruct: x\nQuery: dense retrieval"]:
            self.assertEqual(fixture.fixture_vector(text, 32), backend.fixture_vector(text, 32))


@unittest.skipUnless(importlib.util.find_spec("pymupdf"), "run with: uv run --with pymupdf==1.28.2")
class StructuredPdfTests(unittest.TestCase):
    def test_structured_pdf_has_headings_continuation_table_and_references(self):
        import tempfile

        import pymupdf

        generator = load("create_structured_pdf", HERE / "create_structured_pdf.py")
        with tempfile.TemporaryDirectory() as directory:
            path = generator.create_structured_pdf(Path(directory) / "structured.pdf")
            with pymupdf.open(path) as document:
                self.assertEqual(document.page_count, 4)
                texts = [page.get_text() for page in document]
                self.assertIn("2 Method", texts[1])
                self.assertNotIn("2 Method", texts[2])
                self.assertIn("continues on this page", texts[2])
                tables = document[2].find_tables().tables
                self.assertEqual(len(tables), 1)
                self.assertEqual(tables[0].extract()[0], ["Model", "Recall@10", "Latency (ms)"])
                self.assertIn("References", texts[3])


if __name__ == "__main__":
    unittest.main()
