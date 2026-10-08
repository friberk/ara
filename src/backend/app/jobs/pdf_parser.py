"""Fresh child-process parser: never import PyMuPDF in the API or a worker thread."""

import json
import re
import sys
from pathlib import Path


def parse(path: str) -> dict:
    import pymupdf

    try:
        with pymupdf.open(path) as document:
            if document.needs_pass:
                return {
                    "error": {
                        "code": "PDF_PASSWORD_REQUIRED",
                        "message": "This PDF requires a password.",
                    }
                }
            if document.page_count > 200:
                return {
                    "error": {
                        "code": "PDF_PAGE_LIMIT",
                        "message": "PDFs may contain at most 200 pages.",
                    }
                }
            pages, total = [], 0
            for index, page in enumerate(document):
                text = page.get_text(sort=True)
                total += len(text)
                if total > 4_000_000:
                    return {
                        "error": {
                            "code": "PDF_TEXT_LIMIT",
                            "message": "This PDF contains too much text.",
                        }
                    }
                pages.append(
                    {"page": index + 1, "text": text, "printed_label": page.get_label() or None}
                )
            if not any(page["text"].strip() for page in pages):
                return {
                    "error": {
                        "code": "OCR_REQUIRED",
                        "message": "No readable text found. Upload a text PDF; OCR is disabled.",
                    }
                }
            first = "\n".join(page["text"] for page in pages[:2])
            metadata = document.metadata or {}
            title = (metadata.get("title") or "").strip() or None
            author = (metadata.get("author") or "").strip()
            authors = [x.strip() for x in re.split(r";|\s+and\s+", author) if x.strip()]
            doi = re.search(r"\b10\.\d{4,9}/[^\s<>\"\]]+", first, re.I)
            year = re.search(
                r"(?:published|publication year|copyright|©)\s*[:(]?\s*((?:19|20)\d{2})\b",
                first,
                re.I,
            )
            abstract = re.search(
                r"\bAbstract\s*[:\n]\s*(.{20,10000}?)(?=\n(?:\d+\.?\s*)?Introduction\b|\Z)",
                first,
                re.I | re.S,
            )
            return {
                "metadata": {
                    "title": title,
                    "authors": authors,
                    "year": int(year[1]) if year else None,
                    "doi": doi[0].rstrip(".,;) ").lower() if doi else None,
                    "abstract": abstract[1].strip() if abstract else None,
                },
                "pages": pages,
                "warnings": ["Some pages contain no extractable text."]
                if any(not p["text"].strip() for p in pages)
                else [],
                "extractor_version": f"pymupdf-{pymupdf.VersionBind}",
            }
    except Exception:
        return {
            "error": {"code": "INVALID_PDF", "message": "The PDF could not be opened or extracted."}
        }


if __name__ == "__main__":
    if sys.platform.startswith("linux"):
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (110, 110))
    Path(sys.argv[2]).write_text(json.dumps(parse(sys.argv[1])), encoding="utf-8")
