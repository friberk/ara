"""Explicit synthetic paper/access cases, confined to the deterministic HTTP fixture."""

import os
from pathlib import Path
from urllib.parse import unquote


class FullTextFixture:
    cases = (
        "fulltext-open",
        "fulltext-doi",
        "fulltext-denied",
        "fulltext-html",
        "fulltext-rate",
        "fulltext-unsafe",
        "fulltext-nolink",
    )

    def __init__(self):
        self.granted = set()
        self.pdf_path = Path(
            os.environ.get("FULLTEXT_FIXTURE_PDF", "/fulltext-fixtures/research.pdf")
        )

    def get(self, handler, path, query):
        path = unquote(path)
        case = query.get("search", query.get("query", [""]))[0]
        filter_value = query.get("filter", [""])[0]
        if filter_value.startswith("doi:https://doi.org/10.5555/"):
            case = filter_value.rsplit("/", 1)[-1]
        if path.startswith("/works/"):
            identity = path.rsplit("/", 1)[-1]
            case = next(
                (name for i, name in enumerate(self.cases) if identity == f"W{19001 + i}"), ""
            )
        if path.startswith("/graph/v1/paper/") and not path.endswith("/search"):
            identity = path.split("/paper/", 1)[1]
            case = (
                identity.removeprefix("s2-")
                if identity.startswith("s2-fulltext-")
                else identity.rsplit("/", 1)[-1]
                if identity.startswith("DOI:10.5555/")
                else ""
            )
        if path.startswith("/fulltext/pdf/"):
            case = path.rsplit("/", 1)[-1]
            if case not in self.cases:
                return False
            if case == "fulltext-denied" and case not in self.granted:
                handler.send_json({"error": "Synthetic access denial"}, 403)
            elif case == "fulltext-rate":
                body = b'{"error":"Synthetic rate limit"}'
                handler.send_response(429)
                handler.send_header("Retry-After", "1")
                handler.send_header("Content-Length", str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)
            elif case == "fulltext-unsafe":
                handler.send_response(302)
                handler.send_header("Location", "http://127.0.0.1/private")
                handler.send_header("Content-Length", "0")
                handler.end_headers()
            else:
                body = (
                    b"<html>Institutional sign-in</html>"
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
        if case not in self.cases:
            return False
        semantic = path.startswith("/graph/")
        row = self.paper(case, semantic)
        if path == "/works":
            handler.send_json({"results": [row], "meta": {"count": 1, "next_cursor": None}})
        elif path == "/graph/v1/paper/search":
            handler.send_json({"data": [row], "total": 1})
        else:
            handler.send_json(row)
        return True

    def post(self, handler, path):
        prefix = "/__fulltext_fixture/"
        if not path.startswith(prefix) or not path.endswith("/grant"):
            return False
        case = path[len(prefix) : -len("/grant")]
        if case not in self.cases:
            return False
        length = int(handler.headers.get("Content-Length", "0"))
        if length > 1024:
            handler.send_json({"error": "Too large"}, 413)
            return True
        handler.rfile.read(length)
        self.granted.add(case)
        handler.send_json({"granted": True})
        return True

    def paper(self, case, semantic):
        open_copy = case not in {"fulltext-denied", "fulltext-nolink"}
        url = (
            None
            if case == "fulltext-nolink" or (semantic and case == "fulltext-doi")
            else f"https://arxiv.org/pdf/{case}"
        )
        if semantic:
            return {
                "paperId": "s2-" + case,
                "title": "PDF access fixture: " + case,
                "authors": [{"name": "Ada Researcher"}],
                "year": 2024,
                "abstract": "Synthetic access fixture.",
                "externalIds": {"DOI": "10.5555/" + case},
                "url": "https://www.semanticscholar.org/paper/s2-" + case,
                "isOpenAccess": bool(url and open_copy),
                "openAccessPdf": {"url": url, "status": "GREEN", "license": "CCBY"}
                if url
                else None,
            }
        location = {
            "pdf_url": url,
            "landing_page_url": "https://publisher.example/" + case,
            "is_oa": open_copy,
            "license": "cc-by" if open_copy else None,
            "version": "acceptedVersion" if open_copy else "publishedVersion",
            "source": {"type": "repository" if open_copy else "journal"},
        }
        return {
            "id": f"https://openalex.org/W{19001 + self.cases.index(case)}",
            "display_name": "PDF access fixture: " + case,
            "publication_year": 2024,
            "authorships": [{"author": {"display_name": "Ada Researcher"}}],
            "doi": "https://doi.org/10.5555/" + case,
            "abstract_inverted_index": {"Synthetic": [0], "access": [1]},
            "primary_location": location,
            "best_oa_location": location if open_copy and url else None,
            "locations": [location],
            "open_access": {"is_oa": bool(open_copy and url)},
        }
