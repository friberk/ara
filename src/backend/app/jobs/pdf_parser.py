"""Fresh child-process parser: never import PyMuPDF in the API or a worker thread.

Plain PyMuPDF runs the pre-checks and page text first; PyMuPDF4LLM then adds per-page layout
Markdown and layout boxes. `--legacy` blocks the layout model for the parent's single fallback.
"""

import json
import os
import re
import sys
from pathlib import Path

# Without these the layout model's import hangs under the address-space limit (ARA-071 S2).
THREAD_TUNING = {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "2", "MALLOC_ARENA_MAX": "2"}
ADDRESS_SPACE_LIMIT = 3 * 1024**3 // 2
CPU_SECONDS_LIMIT = 150


def error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def fill_formulas(markdown: str, boxes: list[dict], clip_text) -> tuple[str, list[dict]]:
    """Layout renders display formulas as blank slices; insert the clipped PDF text instead."""
    parts, shifted, shift, cursor = [], [], 0, 0
    for box in sorted(boxes, key=lambda item: (item["start"], item["end"])):
        start, end = box["start"], box["end"]
        replacement = None
        if box["class"] == "formula" and not markdown[start:end].strip():
            text = " ".join(clip_text(box["bbox"]).split())
            if text:
                replacement = f"\n\n$$ {text} $$\n\n"
        if replacement is None:
            shifted.append({**box, "start": start + shift, "end": end + shift})
            continue
        parts.append(markdown[cursor:start])
        parts.append(replacement)
        cursor = end
        shifted.append({**box, "start": start + shift, "end": start + shift + len(replacement)})
        shift += len(replacement) - (end - start)
    parts.append(markdown[cursor:])
    return "".join(parts), shifted


def tune_layout_runtime() -> None:
    os.environ.update(THREAD_TUNING)
    import onnxruntime

    class TunedInferenceSession(onnxruntime.InferenceSession):
        def __init__(self, path_or_bytes, sess_options=None, providers=None, **kwargs):
            options = sess_options or onnxruntime.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            super().__init__(path_or_bytes, sess_options=options, providers=providers, **kwargs)

    onnxruntime.InferenceSession = TunedInferenceSession


def layout_markdown(path: str, document) -> list[tuple[str, list[dict]]]:
    tune_layout_runtime()
    if os.environ.get("APP_ENV") == "test" and os.environ.get("ARA_PARSER_FORCE_LAYOUT_ERROR"):
        raise RuntimeError("Forced layout failure for the fallback test.")
    import pymupdf4llm

    chunks = pymupdf4llm.to_markdown(
        path, page_chunks=True, header=False, footer=False, use_ocr=False, show_progress=False
    )
    pages = []
    for page, chunk in zip(document, chunks, strict=True):
        boxes = [
            {
                "class": box["class"],
                "bbox": list(box["bbox"]),
                "start": box["pos"][0],
                "end": box["pos"][1],
            }
            for box in chunk["page_boxes"]
        ]
        pages.append(
            fill_formulas(
                chunk["text"], boxes, lambda bbox, page=page: page.get_text("text", clip=bbox)
            )
        )
    return pages


def legacy_markdown(path: str) -> list[tuple[str, list[dict]]]:
    # use_layout(False) still loads the ONNX model; blocking the import keeps the fallback small.
    sys.modules["pymupdf.layout"] = None
    import pymupdf4llm

    chunks = pymupdf4llm.to_markdown(path, page_chunks=True, show_progress=False)
    return [(chunk["text"], []) for chunk in chunks]


def extract(document) -> dict:
    pages, total = [], 0
    for index, page in enumerate(document):
        text = page.get_text(sort=True)
        total += len(text)
        if total > 4_000_000:
            return error("PDF_TEXT_LIMIT", "This PDF contains too much text.")
        pages.append({"page": index + 1, "text": text, "printed_label": page.get_label() or None})
    if not any(page["text"].strip() for page in pages):
        return error("OCR_REQUIRED", "No readable text found. Upload a text PDF; OCR is disabled.")
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
    }


def parse(path: str, *, legacy: bool = False) -> dict:
    """Return extracted pages, or an error dict for the documented pre-check failures.

    A failure of the Markdown pass raises, so the parent can retry once in legacy mode.
    """
    import pymupdf

    try:
        document = pymupdf.open(path)
    except Exception:
        return error("INVALID_PDF", "The PDF could not be opened or extracted.")
    with document:
        if document.needs_pass:
            return error("PDF_PASSWORD_REQUIRED", "This PDF requires a password.")
        if document.page_count > 200:
            return error("PDF_PAGE_LIMIT", "PDFs may contain at most 200 pages.")
        try:
            parsed = extract(document)
        except Exception:
            return error("INVALID_PDF", "The PDF could not be opened or extracted.")
        if parsed.get("error"):
            return parsed
        markdown = legacy_markdown(path) if legacy else layout_markdown(path, document)
    import pymupdf4llm

    for page, (text, boxes) in zip(parsed["pages"], markdown, strict=True):
        if not text.strip() and page["text"].strip():
            # Layout files a lone top line as a page header, which header=False drops.
            text, boxes = page["text"], []
        page["markdown"], page["boxes"] = text, boxes
    mode = "legacy" if legacy else "layout"
    parsed["parser"] = f"pymupdf4llm-{mode}"
    parsed["extractor_version"] = f"pymupdf4llm-{pymupdf4llm.__version__}+{mode}"
    return parsed


if __name__ == "__main__":
    if sys.platform.startswith("linux"):
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (ADDRESS_SPACE_LIMIT, ADDRESS_SPACE_LIMIT))
        resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS_LIMIT, CPU_SECONDS_LIMIT))
    result = parse(sys.argv[1], legacy="--legacy" in sys.argv[3:])
    Path(sys.argv[2]).write_text(json.dumps(result), encoding="utf-8")
