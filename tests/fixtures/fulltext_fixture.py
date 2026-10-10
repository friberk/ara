"""Synthetic OpenAlex lookup, content and storage cases, confined to the HTTP fixture (ARA-087)."""

import os
import time
from pathlib import Path
from urllib.parse import unquote

STORAGE = "https://a452eddbbe06eb7d02f4879cee70d29c.r2.cloudflarestorage.com"


class FullTextFixture:
    # Work IDs are W19001 onward, in this order.
    cases = (
        "fulltext-open",
        "fulltext-doi",
        "fulltext-limited",
        "fulltext-html",
        "fulltext-rate",
        "fulltext-unsafe",
        "fulltext-nolink",
        "fulltext-recovery",
        "fulltext-semantic",
    )

    def __init__(self):
        self.granted = set()
        self.held = set()
        self.pdf_path = Path(
            os.environ.get("FULLTEXT_FIXTURE_PDF", "/fulltext-fixtures/research.pdf")
        )

    def work(self, case):
        return f"W{19001 + self.cases.index(case)}"

    def case_of(self, work):
        return next((case for case in self.cases if self.work(case) == work), "")

    def get(self, handler, path, query):
        path = unquote(path)
        if path.startswith("/content/works/"):
            return self.content(handler, path, query)
        if path.startswith("/storage/openalex-pdfs/"):
            return self.storage(handler, path)
        case = query.get("search", query.get("query", [""]))[0]
        filter_value = query.get("filter", [""])[0]
        if filter_value.startswith("doi:https://doi.org/10.5555/"):
            case = filter_value.rsplit("/", 1)[-1]
        if path.startswith("/works/doi:10.5555/"):
            case = path.rsplit("/", 1)[-1]
            if case == "fulltext-semantic":
                handler.send_json({"error": "Not found"}, 404)
                return True
        elif path.startswith("/works/"):
            case = self.case_of(path.rsplit("/", 1)[-1])
        if path.startswith("/graph/v1/paper/") and not path.endswith("/search"):
            identity = path.split("/paper/", 1)[1]
            case = (
                identity.removeprefix("s2-")
                if identity.startswith("s2-fulltext-")
                else identity.rsplit("/", 1)[-1]
                if identity.startswith("DOI:10.5555/")
                else ""
            )
        if case not in self.cases:
            return False
        semantic = path.startswith("/graph/")
        if case == "fulltext-semantic" and not semantic:
            handler.send_json({"results": [], "meta": {"count": 0}})
            return True
        row = self.paper(case, semantic)
        if path == "/works":
            handler.send_json({"results": [row], "meta": {"count": 1, "next_cursor": None}})
        elif path == "/graph/v1/paper/search":
            handler.send_json({"data": [row], "total": 1})
        else:
            handler.send_json(row)
        return True

    def content(self, handler, path, query):
        """content.openalex.org: a key, then 404 or a redirect to a signed storage link."""
        case = self.case_of(path.removeprefix("/content/works/").removesuffix(".pdf"))
        if not query.get("api_key", [""])[0]:
            handler.send_json({"error": "API key required"}, 401)
        elif case in {"", "fulltext-nolink", "fulltext-semantic"}:
            handler.send_json({"error": "Not found"}, 404)
        elif case == "fulltext-limited" and case not in self.granted:
            self.refuse(handler, {"Retry-After": "2"})
        elif case == "fulltext-rate":
            self.refuse(handler, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "3600"})
        else:
            target = (
                "https://arxiv.org/pdf/fulltext-unsafe"
                if case == "fulltext-unsafe"
                else f"{STORAGE}/openalex-pdfs/{case}.pdf?X-Amz-Signature=fixture"
            )
            handler.send_response(302)
            handler.send_header("Location", target)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
        return True

    def refuse(self, handler, headers):
        body = b'{"error":"Rate limit exceeded"}'
        handler.send_response(429)
        for name, value in headers.items():
            handler.send_header(name, value)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def storage(self, handler, path):
        case = path.removeprefix("/storage/openalex-pdfs/").removesuffix(".pdf")
        if case not in self.cases:
            return False
        deadline = time.monotonic() + 20
        while case in self.held and time.monotonic() < deadline:
            time.sleep(0.05)
        if case in self.held:
            handler.send_json({"error": "Synthetic held download timed out"}, 503)
            return True
        body = (
            b"<html>Not a PDF</html>"
            if case == "fulltext-html"
            else self.pdf_path.read_bytes() + f"\n% {case}\n".encode()
        )
        handler.send_response(200)
        handler.send_header(
            "Content-Type", "text/html" if case == "fulltext-html" else "application/pdf"
        )
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return True

    def post(self, handler, path):
        prefix = "/__fulltext_fixture/"
        if not path.startswith(prefix):
            return False
        case, _, action = path[len(prefix) :].rpartition("/")
        if case not in self.cases or action not in {"grant", "hold", "release"}:
            return False
        length = int(handler.headers.get("Content-Length", "0"))
        if length > 1024:
            handler.send_json({"error": "Too large"}, 413)
            return True
        handler.rfile.read(length)
        if action == "grant":
            self.granted.add(case)
        elif action == "hold":
            self.held.add(case)
        else:
            self.held.discard(case)
        handler.send_json({"granted": case in self.granted, "held": case in self.held})
        return True

    def paper(self, case, semantic):
        if semantic:
            return {
                "paperId": "s2-" + case,
                "title": "PDF access fixture: " + case,
                "authors": [{"name": "Ada Researcher"}],
                "year": 2024,
                "abstract": "Synthetic access fixture.",
                "externalIds": {"DOI": "10.5555/" + case},
                "url": "https://www.semanticscholar.org/paper/s2-" + case,
                "isOpenAccess": False,
                "openAccessPdf": None,
            }
        stored = case not in {"fulltext-nolink", "fulltext-semantic"}
        return {
            "id": f"https://openalex.org/{self.work(case)}",
            "display_name": "PDF access fixture: " + case,
            "publication_year": 2024,
            "authorships": [{"author": {"display_name": "Ada Researcher"}}],
            "doi": "https://doi.org/10.5555/" + case,
            "abstract_inverted_index": {"Synthetic": [0], "access": [1]},
            "primary_location": {
                "landing_page_url": "https://publisher.example/" + case,
                "source": {"type": "journal"},
            },
            "has_content": {"pdf": stored, "grobid_xml": stored},
        }
