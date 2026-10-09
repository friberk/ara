"""Fresh child-process parser: never import PyMuPDF in the API or a worker thread.

Plain PyMuPDF runs the pre-checks and page text first; PyMuPDF4LLM then adds per-page layout
Markdown and layout boxes. `--legacy` blocks the layout model for the parent's single fallback.
"""

import json
import os
import re
import sys
import unicodedata
from pathlib import Path

# Without these the layout model's import hangs under the address-space limit (ARA-071 S2).
THREAD_TUNING = {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "2", "MALLOC_ARENA_MAX": "2"}
ADDRESS_SPACE_LIMIT = 3 * 1024**3 // 2
CPU_SECONDS_LIMIT = 150


# C0 controls other than tab, newline and carriage return, plus DEL. TeX math-extension fonts
# encode big delimiters at code points 0 and 1, and PostgreSQL text rejects NUL.
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
DOI = re.compile(r"\b10\.\d{4,9}/[^\s<>\"\]]+", re.I)
ARXIV = re.compile(r"\barXiv:\s*(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?", re.I)
# Info titles that name a file or a toolchain step rather than the paper (ARA-086).
FILE_EXTENSION = re.compile(
    r"\.(?:dvi|tex|ltx|pdf|ps|eps|docx?|rtf|odt|txt|md|indd|qxd|qxp|pages|pptx?|xlsx?|html?)$",
    re.I,
)
APPLICATION = re.compile(r"(?:microsoft\s+)?(?:word|powerpoint|excel)\s+-\s", re.I)
IDENTIFIER = re.compile(r"(?:doi|arxiv|pii|isbn|issn)\s*:", re.I)
PLACEHOLDER = re.compile(
    r"(?:untitled(?: document)?|document|title|paper|article|manuscript|draft|main|template|"
    r"slides|presentation|layout|none|null|unknown|no title)(?:[\s_-]*\d+)?",
    re.I,
)
PLACEHOLDER_AUTHOR = re.compile(
    r"(?:user|admin(?:istrator)?|author|owner|unknown|anonymous|editor|ieee|acm|springer|"
    r"elsevier|microsoft.*)\d*",
    re.I,
)
# First-page lines that are never part of a title: stamps, links, venue and rights notices.
NOT_TITLE = re.compile(
    r"^(?:arxiv|doi|https?:|www\.|©|copyright|preprint|proceedings|published|accepted|received|"
    r"vol\.|volume|issn|isbn)|@|https?://",
    re.I,
)


def error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def storable(text: str) -> str:
    """U+FFFD for control characters, as layout Markdown renders them; offsets stay valid."""
    return CONTROL.sub("\ufffd", text)


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


def squashed(text: str) -> str:
    """Letters and digits only, so line breaks, hyphens and case never decide a comparison."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[\W_]+", "", ascii_text).lower()


def artifact_title(value: str | None) -> bool:
    """Whether a PDF Info title names a file, an application or a placeholder, not a paper."""
    text = " ".join((value or "").split())
    if sum(character.isalpha() for character in text) < 4 or "\\" in text:
        return True
    if FILE_EXTENSION.search(text) or APPLICATION.match(text) or IDENTIFIER.match(text):
        return True
    # A single token with separators or digits is a file stem, such as final_v2 or sec18-han.
    return bool(PLACEHOLDER.fullmatch(text) or (" " not in text and re.search(r"[_/\d]", text)))


def join_lines(lines: list[str]) -> str:
    title = ""
    for line in lines:
        if title.endswith("-"):
            # A hyphen before a lowercase continuation splits a word; otherwise it is a compound.
            title = title[:-1] + line if line[:1].islower() else title + line
        else:
            title = f"{title} {line}" if title else line
    return title


def page_title(page) -> str | None:
    """The first page's largest horizontal text near the top, as printed (ARA-086).

    Rotated text such as arXiv's margin stamp is skipped. A title is set larger than the body
    text (the size carrying most characters), and a group that does not read like a title
    gives way to the next size down.
    """
    lines, weights = [], {}
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            dx, dy = line["dir"]
            spans = [span for span in line["spans"] if span["text"].strip()]
            if dx < 0.99 or abs(dy) > 0.01 or not spans:
                continue
            text = " ".join(storable("".join(span["text"] for span in spans)).split())
            size = round(max(span["size"] for span in spans), 1)
            weights[size] = weights.get(size, 0) + len(text)
            x0, top, _, bottom = line["bbox"]
            if (
                top <= page.rect.height * 0.6
                and re.search(r"[^\W\d_]", text)
                and not NOT_TITLE.search(text)
            ):
                lines.append((top, x0, bottom, size, text))
    if not lines:
        return None
    body = max(weights, key=weights.get)
    lines.sort()
    sizes = sorted({line[3] for line in lines if line[3] >= body * 1.15}, reverse=True)
    for size in sizes[:3]:
        group, end = [], None
        for top, _, bottom, line_size, text in lines:
            if abs(line_size - size) > 0.5:
                if group:
                    break
                continue
            if group and top - end > size * 1.2:
                break
            group.append(text)
            end = bottom
        title = join_lines(group)
        words = title.split()
        if 2 <= len(words) <= 40 and sum(character.isalpha() for character in title) >= 8:
            return title
    return None


def choose_title(info_title: str | None, printed: str | None, first_pages: str) -> str | None:
    """A usable Info title wins only when the first pages print it; else the printed title."""
    usable = info_title if info_title and not artifact_title(info_title) else None
    if usable and (printed is None or squashed(usable) in squashed(first_pages)):
        return usable
    return printed or usable


def embedded_text(document, metadata: dict) -> str:
    try:
        xmp = document.get_xml_metadata() or ""
    except Exception:
        xmp = ""
    fields = [metadata.get("subject"), metadata.get("keywords"), xmp[:200_000]]
    return "\n".join(value for value in fields if isinstance(value, str))


def extract(document) -> dict:
    pages, total = [], 0
    for index, page in enumerate(document):
        text = storable(page.get_text(sort=True))
        total += len(text)
        if total > 4_000_000:
            return error("PDF_TEXT_LIMIT", "This PDF contains too much text.")
        pages.append({"page": index + 1, "text": text, "printed_label": page.get_label() or None})
    if not any(page["text"].strip() for page in pages):
        return error("OCR_REQUIRED", "No readable text found. Upload a text PDF; OCR is disabled.")
    first = "\n".join(page["text"] for page in pages[:2])
    metadata = document.metadata or {}
    info_title = " ".join(storable(metadata.get("title") or "").split()) or None
    title = choose_title(info_title, page_title(document[0]), first)
    author = storable(metadata.get("author") or "").strip()
    authors = [
        name
        for name in (x.strip() for x in re.split(r";|\s+and\s+", author))
        if name and not PLACEHOLDER_AUTHOR.fullmatch(name) and not re.search(r"[\d\\/@]", name)
    ]
    # Publishers embed the paper's own DOI; one in the text may belong to a cited reference.
    doi = DOI.search(embedded_text(document, metadata)) or DOI.search(first)
    arxiv = ARXIV.search(pages[0]["text"])
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
            "arxiv_id": arxiv[1] if arxiv else None,
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
        page["markdown"], page["boxes"] = storable(text), boxes
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
